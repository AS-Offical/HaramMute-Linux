"""Local processing helpers for HaramMute (Linux build).

Pure-Python replacement for the compiled Windows ``local_processing`` module:

* yt-dlp download with browser-cookie fallback chain
* source audio -> WAV conversion + duration probing (ffprobe/ffmpeg)
* audio chunk splitting via ffmpeg
* device auto-detection (CUDA via ONNX Runtime, else CPU)
* bundled model-cache seeding for audio-separator
* UVR-MDX-NET vocal separation via audio-separator with retries
* vocals transcode to MP3 with loudness normalization

DirectML support from the Windows build is intentionally absent; Linux
builds use CUDAExecutionProvider when available, otherwise CPU.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .config import settings
from .limits import MAX_VIDEO_SECONDS

logger = logging.getLogger("app.local_processing")
_download_start_lock = threading.Lock()
_last_download_started = 0.0

DEFAULT_MODEL_NAME = os.environ.get("MUSIC_REMOVER_MODEL_NAME", "UVR-MDX-NET-Voc_FT.onnx")

# Linux browser cookie-store locations used for yt-dlp --cookies-from-browser.
_BROWSER_COOKIE_GLOBS = {
    "chrome": (
        "~/.config/google-chrome/*/Cookies",
        "~/.var/app/com.google.Chrome/config/google-chrome/*/Cookies",
    ),
    "chromium": (
        "~/.config/chromium/*/Cookies",
        "~/.var/app/org.chromium.Chromium/config/chromium/*/Cookies",
    ),
    "brave": (
        "~/.config/BraveSoftware/Brave-Browser/*/Cookies",
        "~/.var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser/*/Cookies",
    ),
    "edge": ("~/.config/microsoft-edge/*/Cookies",),
    "firefox": (
        "~/.mozilla/firefox/*/cookies.sqlite",
        "~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/cookies.sqlite",
    ),
}


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bundled_model_cache_dir() -> Path:
    return project_root() / "assets" / "model_cache" / "audio-separator"


def ffmpeg_binary() -> str:
    configured = os.environ.get("MUSIC_REMOVER_FFMPEG_BINARY") or settings.ffmpeg_binary
    return shutil.which(configured) or configured


def ffprobe_binary() -> Optional[str]:
    return os.environ.get("MUSIC_REMOVER_FFPROBE_BINARY") or shutil.which("ffprobe")


# ---------------------------------------------------------------------------
# Device detection (no torch dependency, mirrors upstream behaviour)
# ---------------------------------------------------------------------------

def _import_onnxruntime():
    try:
        import onnxruntime as ort
        return ort
    except ImportError:
        return None


def available_onnx_providers() -> list[str]:
    ort = _import_onnxruntime()
    if ort is None:
        return []
    try:
        return list(ort.get_available_providers())
    except Exception:
        return []


def resolve_device(force_cpu: bool = False) -> tuple[str, list[str]]:
    """Return ``(device_label, onnx_providers)`` for this machine."""
    if force_cpu:
        return "cpu", ["CPUExecutionProvider"]
    available = set(available_onnx_providers())
    for provider, label in (
        ("CUDAExecutionProvider", "nvidia-cuda"),
        ("OpenVINOExecutionProvider", "intel-openvino"),
        ("MIGraphXExecutionProvider", "amd-migraphx"),
    ):
        if provider in available:
            return label, [provider, "CPUExecutionProvider"]
    return "cpu", ["CPUExecutionProvider"]


# ---------------------------------------------------------------------------
# Model cache seeding
# ---------------------------------------------------------------------------

def seed_model_cache(target_dir: Path) -> None:
    """Seed audio-separator's model cache from the bundled assets once."""
    source = bundled_model_cache_dir()
    if not source.exists():
        logger.warning("Bundled model assets missing at %s", source)
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for item in source.iterdir():
        destination = target_dir / item.name
        if not destination.exists():
            shutil.copy2(item, destination)
            copied.append(item.name)
    if copied:
        logger.info("Seeded audio-separator cache from bundled files: %s", ", ".join(sorted(copied)))


# ---------------------------------------------------------------------------
# Browser cookie detection
# ---------------------------------------------------------------------------

def detect_cookie_browsers() -> list[str]:
    """Return installed browsers with detectable cookie stores."""
    import glob

    found = []
    for browser, patterns in _BROWSER_COOKIE_GLOBS.items():
        matches = []
        for pattern in patterns:
            try:
                matches.extend(glob.glob(os.path.expanduser(pattern)))
            except OSError:
                continue
        if matches:
            # yt-dlp reads the browser database directly; the browser binary
            # itself does not need to be present on PATH.
            found.append(browser)
    logger.info("Available browsers for cookies: %s", found or "none")
    return found


# ---------------------------------------------------------------------------
# yt-dlp download
# ---------------------------------------------------------------------------

def _ytdlp_base_args() -> list[str]:
    executable = shutil.which(settings.yt_dlp_binary)
    args = [executable] if executable else [sys.executable, "-u", "-m", "yt_dlp"]
    deno = shutil.which(settings.deno_binary)
    if deno:
        args += ["--js-runtimes", f"deno:{deno}", "--remote-components", "ejs:github"]
    args += ["--no-warnings"]
    return args


def fetch_metadata(url: str, cookies_browser: Optional[str] = None) -> Optional[dict]:
    """Preflight metadata lookup; failures are non-fatal."""
    command = _ytdlp_base_args() + [
        "--dump-single-json", "--no-playlist", "--skip-download",
        "--extractor-retries", "2", "--fragment-retries", "1",
    ]
    if cookies_browser:
        command += ["--cookies-from-browser", cookies_browser]
    command.append(url)
    logger.debug("Metadata command: %s", " ".join(command))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            return json.loads(result.stdout)
        logger.debug(
            "yt-dlp metadata preflight failed; continuing to download [%s]",
            (result.stderr or "").strip().splitlines()[-1:] or "unknown",
        )
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        logger.debug("yt-dlp metadata preflight error: %s", exc)
    return None


def download_audio(
    url: str,
    work_dir: Path,
    progress_callback: Optional[Callable[[float], None]] = None,
    delay_between_attempts: float = 0.0,
) -> Path:
    """Download best-quality audio via yt-dlp, trying each cookie browser.

    Returns the path of ``work_dir/source.<ext>``.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    _clear_partial_downloads(work_dir)
    output_template = str(work_dir / "source.%(ext)s")
    format_selector = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
    common = [
        "-f", format_selector,
        "--no-playlist",
        "-o", output_template,
        "--extractor-retries", "5",
        "--fragment-retries", "10",
        "--socket-timeout", "30",
        "--newline",
        "-N", "4",
    ]

    if settings.cookies_file or settings.skip_browser_cookies:
        attempts: list[Optional[str]] = [None]
    elif settings.browser_for_cookies:
        attempts = [settings.browser_for_cookies, None]
    else:
        attempts = detect_cookie_browsers() + [None]
    global _last_download_started
    last_error: Optional[str] = None

    for index, browser in enumerate(attempts):
        if index:
            _clear_partial_downloads(work_dir)
        label = f"{browser} cookies" if browser else "without cookies"
        if browser is None and attempts[:-1]:
            logger.warning("Trying download without cookies...")
        else:
            logger.info("Trying download with %s...", label)

        metadata = fetch_metadata(url, browser)
        duration = metadata.get("duration") if metadata else None
        if isinstance(duration, (int, float)) and duration > MAX_VIDEO_SECONDS:
            raise ValueError(
                f"Media is longer than the 90-minute processing limit ({duration / 60:.1f} minutes)"
            )

        command = _ytdlp_base_args() + common
        if browser:
            command += ["--cookies-from-browser", browser]
        elif settings.cookies_file:
            command += ["--cookies", str(settings.cookies_file)]
        command.append(url)
        logger.debug("Command: %s", " ".join(command))

        with _download_start_lock:
            minimum_delay = max(delay_between_attempts, settings.download_delay)
            wait_for = minimum_delay - (time.monotonic() - _last_download_started)
            if _last_download_started and wait_for > 0:
                time.sleep(wait_for)
            _last_download_started = time.monotonic()

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        error_lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            lowered = line.lower()
            if "[download]" in line and "%" in line and progress_callback:
                try:
                    percent = float(line.split("%", 1)[0].rsplit(None, 1)[-1])
                    progress_callback(max(0.0, min(1.0, percent / 100.0)))
                except ValueError:
                    pass
            elif line.startswith("ERROR"):
                error_lines.append(line)

        code = process.wait()
        downloaded = _find_downloaded(work_dir)
        if code == 0 and downloaded is not None:
            logger.info("Downloaded: %s", downloaded)
            return downloaded

        last_error = "; ".join(error_lines[-1:]) or f"exit code {code}"
        logger.warning("%s failed: %s", label, last_error[:300])

    raise RuntimeError(f"All yt-dlp download attempts failed for {url}: {last_error}")


def _find_downloaded(work_dir: Path) -> Optional[Path]:
    candidates = sorted(
        (p for p in work_dir.iterdir() if p.is_file() and p.stem == "source"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _clear_partial_downloads(work_dir: Path) -> None:
    """Remove incomplete/stale yt-dlp outputs before another attempt."""
    for path in work_dir.glob("source.*"):
        if path.is_file():
            try:
                path.unlink()
            except OSError as exc:
                logger.debug("Could not remove partial download %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Audio conversion / probing / splitting
# ---------------------------------------------------------------------------

def convert_to_wav(source: Path, work_dir: Path) -> Path:
    """Normalize all inputs to the separator's expected stereo 44.1kHz WAV."""
    target = work_dir / "normalized-source.wav"
    command = [
        ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-ar", "44100", "-ac", "2",
        str(target),
    ]
    logger.debug("Converting %s to WAV for better performance...", source.name)
    subprocess.run(command, check=True, capture_output=True)
    logger.info("Converted to WAV: %s", target)
    return target


def probe_duration(path: Path) -> float:
    """Probe media duration in seconds using ffprobe, falling back to ffmpeg."""
    ffprobe = ffprobe_binary()
    if ffprobe:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            try:
                return float(result.stdout.strip())
            except ValueError:
                pass
        logger.warning("ffprobe failed, falling back to ffmpeg for duration")
    command = [
        ffmpeg_binary(), "-hide_banner", "-i", str(path),
        "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    for line in (result.stderr or "").splitlines():
        if "time=" in line:
            stamp = line.split("time=")[1].split(" ")[0]
            parts = [float(p) for p in stamp.split(":")]
            seconds = parts[-1]
            if len(parts) > 1:
                seconds += parts[-2] * 60
            if len(parts) > 2:
                seconds += parts[-3] * 3600
            return seconds
    raise RuntimeError(f"Could not determine duration of {path}")


def split_audio_chunk(wav_path: Path, start: float, end: float, out_path: Path) -> Path:
    """Split a chunk from the source WAV using ffmpeg."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{max(0.05, end - start):.3f}",
        "-i", str(wav_path),
        "-ar", "44100", "-ac", "2",
        str(out_path),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return out_path


# ---------------------------------------------------------------------------
# Vocal separation via audio-separator
# ---------------------------------------------------------------------------

def _patch_librosa_get_duration() -> None:
    """audio-separator 0.41 calls librosa.get_duration(filename=...), a kwarg
    removed in librosa 0.11. Shim it to the new ``path=`` form."""
    import inspect

    import librosa

    if "filename" in inspect.signature(librosa.get_duration).parameters:
        return
    original = librosa.get_duration

    def compat(*args, **kwargs):
        if "filename" in kwargs:
            kwargs["path"] = kwargs.pop("filename")
        return original(*args, **kwargs)

    librosa.get_duration = compat


def _pick_vocals_output(files: list[str], output_dir: Path) -> Optional[Path]:
    candidates = []
    for name in files:
        path = Path(name)
        if not path.is_absolute():
            path = output_dir / path.name
        candidates.append(path)
        if not path.exists():
            # audio-separator may write next to the input file
            alternative = path.parent.parent / "work" / path.name
            if alternative.exists():
                candidates[-1] = alternative

    for path in candidates:
        if "vocal" in path.stem.lower():
            return path
    # MDX models emit exactly two stems; vocals is usually the first.
    return candidates[0] if candidates else None


def separate_vocals(
    wav_path: Path,
    output_dir: Path,
    model_cache_dir: Path,
    force_cpu: bool = False,
    max_attempts: int = 3,
) -> dict:
    """Run UVR (audio-separator) locally; returns {'vocals': Path, 'seconds': float}.

    Retries transient runtime/model-cache errors up to ``max_attempts``.
    """
    _patch_librosa_get_duration()
    from audio_separator.separator import Separator

    output_dir.mkdir(parents=True, exist_ok=True)
    model_cache_dir.mkdir(parents=True, exist_ok=True)
    seed_model_cache(model_cache_dir)

    device, providers = resolve_device(force_cpu)
    import onnxruntime  # noqa: F401  (version reporting only)
    runtime_label = (
        f"onnxruntime={onnxruntime.__version__};providers={','.join(providers)}"
    )

    last_error: Optional[Exception] = None
    model_repaired = False
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        try:
            separator = Separator(
                model_file_dir=str(model_cache_dir),
                output_dir=str(output_dir),
                output_format="WAV",
            )
            # audio-separator 0.41.0 consumes this value when constructing
            # its ONNX session; its default Linux selection only chooses CUDA.
            separator.onnx_execution_provider = providers
            logger.info(
                "Separating audio with UVR (audio-separator): %s [device=%s, model=%s, "
                "model_cache=%s, runtime=%s, attempt=%d/%d]",
                wav_path, device, DEFAULT_MODEL_NAME, model_cache_dir, runtime_label,
                attempt, max_attempts,
            )
            separator.load_model(model_filename=DEFAULT_MODEL_NAME)
            output_files = separator.separate(str(wav_path))
            vocals = _pick_vocals_output(output_files, output_dir)
            if vocals is None or not vocals.exists():
                raise RuntimeError(f"No vocals stem produced (outputs={output_files})")
            for output_name in output_files:
                output_path = Path(output_name)
                if not output_path.is_absolute():
                    output_path = output_dir / output_path.name
                if output_path != vocals and output_path.exists():
                    try:
                        output_path.unlink()
                    except OSError as cleanup_error:
                        logger.debug("Could not remove unused stem %s: %s", output_path, cleanup_error)
            elapsed = time.monotonic() - started
            return {
                "vocals": vocals.resolve(),
                "seconds": round(elapsed, 2),
                "device": device,
                "providers": list(providers),
            }
        except Exception as exc:  # noqa: BLE001 - retry any runtime failure
            last_error = exc
            logger.warning("Separation attempt %d/%d failed: %s", attempt, max_attempts, exc)
            error_text = str(exc).lower()
            model_path = model_cache_dir / DEFAULT_MODEL_NAME
            looks_corrupt = any(
                phrase in error_text
                for phrase in ("protobuf parsing failed", "invalid protobuf", "corrupt model")
            )
            if looks_corrupt and not model_repaired and model_path.is_file():
                logger.warning("The cached ONNX model appears corrupt; removing it for a clean retry")
                try:
                    model_path.unlink()
                    model_repaired = True
                except OSError as cleanup_error:
                    logger.warning("Could not remove corrupt model cache %s: %s", model_path, cleanup_error)
            if device != "cpu":
                logger.warning("Hardware ONNX provider failed; retrying with CPU fallback")
                device, providers = "cpu", ["CPUExecutionProvider"]
                runtime_label = (
                    f"onnxruntime={onnxruntime.__version__};providers={','.join(providers)}"
                )
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Vocal separation failed after {max_attempts} attempts: {last_error}")


# ---------------------------------------------------------------------------
# MP3 packaging
# ---------------------------------------------------------------------------

def transcode_to_mp3(source: Path, target: Path, quality: int = 4) -> Path:
    """Encode a WAV/PCM input to MP3 VBR with loudness normalization."""
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
        "-c:a", "libmp3lame", "-q:a", str(quality),
        str(target),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return target


def concatenate_wav_chunks_to_mp3(
    chunks: list[Path], target: Path, quality: int = 4
) -> Path:
    """Join sequential PCM vocal chunks and encode one continuous MP3."""
    if not chunks:
        raise ValueError("Cannot assemble vocals without completed chunks")
    target.parent.mkdir(parents=True, exist_ok=True)
    concat_list = target.parent / f".{target.stem}-concat.txt"

    def quote_concat_path(path: Path) -> str:
        escaped = str(path.resolve()).replace("'", "'\\''")
        return f"file '{escaped}'"

    try:
        concat_list.write_text(
            "\n".join(quote_concat_path(path) for path in chunks) + "\n",
            encoding="utf-8",
        )
        command = [
            ffmpeg_binary(), "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-af", "loudnorm=I=-16:LRA=11:TP=-1.5",
            "-c:a", "libmp3lame", "-q:a", str(quality),
            str(target),
        ]
        subprocess.run(command, check=True, capture_output=True)
    finally:
        try:
            concat_list.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove temporary concat list %s: %s", concat_list, exc)
    return target
