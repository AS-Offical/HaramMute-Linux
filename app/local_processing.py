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
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("app.local_processing")

DEFAULT_MODEL_NAME = os.environ.get("MUSIC_REMOVER_MODEL_NAME", "UVR-MDX-NET-Voc_FT.onnx")

# Linux browser cookie-store locations used for yt-dlp --cookies-from-browser.
_BROWSER_COOKIE_GLOBS = {
    "chrome": "~/.config/google-chrome/*/Cookies",
    "chromium": "~/.config/chromium/*/Cookies",
    "brave": "~/.config/BraveSoftware/Brave-Browser/*/Cookies",
    "edge": "~/.config/microsoft-edge/*/Cookies",
    "firefox": "~/.mozilla/firefox/*/cookies.sqlite",
}


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def bundled_model_cache_dir() -> Path:
    return project_root() / "assets" / "model_cache" / "audio-separator"


def ffmpeg_binary() -> str:
    return os.environ.get("MUSIC_REMOVER_FFMPEG_BINARY") or shutil.which("ffmpeg") or "ffmpeg"


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


def _cuda_available() -> bool:
    ort = _import_onnxruntime()
    if ort is None:
        return False
    try:
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def resolve_device(force_cpu: bool = False) -> tuple[str, list[str]]:
    """Return ``(device_label, onnx_providers)`` for this machine."""
    if force_cpu:
        return "cpu", ["CPUExecutionProvider"]
    if _cuda_available():
        return "cuda", ["CUDAExecutionProvider", "CPUExecutionProvider"]
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
    for browser, pattern in _BROWSER_COOKIE_GLOBS.items():
        try:
            matches = glob.glob(os.path.expanduser(pattern))
        except OSError:
            matches = []
        if matches and shutil.which(browser):
            found.append(browser)
        elif matches and browser == "firefox":
            # firefox binary may be named differently but store exists
            found.append(browser)
    logger.info("Available browsers for cookies: %s", found or "none")
    return found


# ---------------------------------------------------------------------------
# yt-dlp download
# ---------------------------------------------------------------------------

def _ytdlp_base_args() -> list[str]:
    args = [sys.executable, "-u", "-m", "yt_dlp", "--no-warnings"]
    if shutil.which("deno"):
        args += ["--js-runtimes", "deno", "--remote-components", "ejs:github"]
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

    attempts: list[Optional[str]] = detect_cookie_browsers() + [None]
    last_error: Optional[str] = None

    for index, browser in enumerate(attempts):
        if delay_between_attempts and index > 0:
            time.sleep(delay_between_attempts)

        label = f"{browser} cookies" if browser else "without cookies"
        if browser is None and attempts[:-1]:
            logger.warning("Trying download without cookies...")
        else:
            logger.info("Trying download with %s...", label)

        fetch_metadata(url, browser)

        command = _ytdlp_base_args() + common
        if browser:
            command += ["--cookies-from-browser", browser]
        command.append(url)
        logger.debug("Command: %s", " ".join(command))

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


# ---------------------------------------------------------------------------
# Audio conversion / probing / splitting
# ---------------------------------------------------------------------------

def convert_to_wav(source: Path, work_dir: Path) -> Path:
    """Convert downloaded audio to WAV for compatibility with the separator."""
    if source.suffix.lower() == ".wav":
        return source
    target = work_dir / "source.wav"
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
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        try:
            separator = Separator(
                model_file_dir=str(model_cache_dir),
                output_dir=str(output_dir),
                output_format="WAV",
            )
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
            elapsed = time.monotonic() - started
            return {"vocals": vocals.resolve(), "seconds": round(elapsed, 2)}
        except Exception as exc:  # noqa: BLE001 - retry any runtime failure
            last_error = exc
            logger.warning("Separation attempt %d/%d failed: %s", attempt, max_attempts, exc)
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
