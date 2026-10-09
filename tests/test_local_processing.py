from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import local_processing as lp


def test_binary_resolution_and_device_detection(monkeypatch):
    monkeypatch.setattr(lp.settings, "ffmpeg_binary", "ffmpeg")
    monkeypatch.setattr(lp.settings, "yt_dlp_binary", "yt-dlp")
    monkeypatch.setattr(lp.settings, "deno_binary", "deno")
    monkeypatch.setattr(lp.shutil, "which", lambda name: f"/bin/{name}")
    assert lp.ffmpeg_binary() == "/bin/ffmpeg"
    assert lp.ffprobe_binary() == "/bin/ffprobe"
    assert lp._ytdlp_base_args() == ["/bin/yt-dlp", "--js-runtimes", "deno:/bin/deno", "--remote-components", "ejs:github", "--no-warnings"]
    monkeypatch.setattr(lp, "available_onnx_providers", lambda: ["MIGraphXExecutionProvider", "CUDAExecutionProvider"])
    assert lp.resolve_device() == ("nvidia-cuda", ["CUDAExecutionProvider", "CPUExecutionProvider"])
    assert lp.resolve_device(True) == ("cpu", ["CPUExecutionProvider"])


def test_binary_environment_override_and_python_module_fallback(monkeypatch):
    monkeypatch.setenv("MUSIC_REMOVER_FFMPEG_BINARY", "/custom/ffmpeg")
    monkeypatch.setenv("MUSIC_REMOVER_FFPROBE_BINARY", "/custom/ffprobe")
    monkeypatch.setattr(lp.shutil, "which", lambda _: None)
    assert lp.ffmpeg_binary() == "/custom/ffmpeg"
    assert lp.ffprobe_binary() == "/custom/ffprobe"
    assert lp._ytdlp_base_args()[:4] == [sys.executable, "-u", "-m", "yt_dlp"]
    assert lp.project_root().name == "HaramMute-Linux"
    assert lp.bundled_model_cache_dir().parts[-3:] == ("assets", "model_cache", "audio-separator")


def test_onnx_import_error(monkeypatch):
    import builtins
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == "onnxruntime": raise ImportError("not installed")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    assert lp._import_onnxruntime() is None


def test_onnx_import_success(monkeypatch):
    module = SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"])
    monkeypatch.setitem(sys.modules, "onnxruntime", module)
    assert lp._import_onnxruntime() is module


@pytest.mark.parametrize("providers, expected", [
    (["OpenVINOExecutionProvider"], "intel-openvino"),
    (["MIGraphXExecutionProvider"], "amd-migraphx"),
    ([], "cpu"),
])
def test_resolve_device_fallbacks(monkeypatch, providers, expected):
    monkeypatch.setattr(lp, "available_onnx_providers", lambda: providers)
    assert lp.resolve_device()[0] == expected


def test_provider_import_errors_are_safe(monkeypatch):
    monkeypatch.setattr(lp, "_import_onnxruntime", lambda: None)
    assert lp.available_onnx_providers() == []
    monkeypatch.setattr(lp, "_import_onnxruntime", lambda: SimpleNamespace(get_available_providers=lambda: 1 / 0))
    assert lp.available_onnx_providers() == []


def test_seed_model_cache_copies_only_missing_and_missing_source(monkeypatch, tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "model.onnx").write_text("model")
    target.mkdir()
    (target / "model.onnx").write_text("existing")
    (source / "other.onnx").write_text("other")
    monkeypatch.setattr(lp, "bundled_model_cache_dir", lambda: source)
    lp.seed_model_cache(target)
    assert (target / "model.onnx").read_text() == "existing"
    assert (target / "other.onnx").read_text() == "other"
    monkeypatch.setattr(lp, "bundled_model_cache_dir", lambda: tmp_path / "missing")
    lp.seed_model_cache(target)


def test_detect_cookie_browsers(monkeypatch):
    monkeypatch.setattr("glob.glob", lambda pattern: [pattern] if "firefox" in pattern else [])
    assert lp.detect_cookie_browsers() == ["firefox"]


def test_cookie_detection_skips_glob_oserrors(monkeypatch):
    monkeypatch.setattr("glob.glob", lambda _: (_ for _ in ()).throw(OSError("denied")))
    assert lp.detect_cookie_browsers() == []


def test_metadata_success_and_failures(monkeypatch):
    monkeypatch.setattr(lp, "_ytdlp_base_args", lambda: ["yt-dlp"])
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"duration":12}', stderr=""))
    assert lp.fetch_metadata("url", "firefox") == {"duration": 12}
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="bad", stderr="failed"))
    assert lp.fetch_metadata("url") is None
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("no executable")))
    assert lp.fetch_metadata("url") is None
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="{broken", stderr=""))
    assert lp.fetch_metadata("url") is None
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("yt-dlp", 1)))
    assert lp.fetch_metadata("url") is None


def test_download_audio_success_and_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "fetch_metadata", lambda *a: {"duration": 10})
    monkeypatch.setattr(lp, "_ytdlp_base_args", lambda: ["yt-dlp"])
    monkeypatch.setattr(lp, "detect_cookie_browsers", lambda: [])
    monkeypatch.setattr(lp, "_last_download_started", 0)

    class Process:
        stdout = iter(["[download] 50.0% of 1MiB", "[download] 101%", "noise"])
        def wait(self):
            (tmp_path / "source.m4a").write_text("audio")
            return 0

    monkeypatch.setattr(lp.subprocess, "Popen", lambda *a, **k: Process())
    seen = []
    assert lp.download_audio("url", tmp_path, seen.append) == tmp_path / "source.m4a"
    assert seen == [0.5, 1.0]


def test_download_duration_limit_and_failed_attempt(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "fetch_metadata", lambda *a: {"duration": lp.MAX_VIDEO_SECONDS + 1})
    with pytest.raises(ValueError, match="90-minute"):
        lp.download_audio("url", tmp_path)
    monkeypatch.setattr(lp, "fetch_metadata", lambda *a: None)
    monkeypatch.setattr(lp, "_ytdlp_base_args", lambda: ["yt-dlp"])
    monkeypatch.setattr(lp, "detect_cookie_browsers", lambda: [])
    monkeypatch.setattr(lp, "_last_download_started", 0)

    class Process:
        stdout = iter(["ERROR: unavailable"])
        def wait(self): return 1
    monkeypatch.setattr(lp.subprocess, "Popen", lambda *a, **k: Process())
    with pytest.raises(RuntimeError, match="All yt-dlp"):
        lp.download_audio("url", tmp_path)


def test_download_cookie_retry_clears_partial_and_uses_config(monkeypatch, tmp_path):
    monkeypatch.setattr(lp.settings, "cookies_file", None)
    monkeypatch.setattr(lp.settings, "skip_browser_cookies", False)
    monkeypatch.setattr(lp.settings, "browser_for_cookies", "firefox")
    monkeypatch.setattr(lp.settings, "download_delay", 0)
    monkeypatch.setattr(lp, "fetch_metadata", lambda *a: None)
    monkeypatch.setattr(lp, "_ytdlp_base_args", lambda: ["yt-dlp"])
    monkeypatch.setattr(lp, "_last_download_started", 0)
    calls = []
    class Process:
        def __init__(self, n): self.stdout = iter(["ERROR: denied"] if n == 0 else [])
        def wait(self):
            if len(calls) == 2: (tmp_path / "source.webm").write_text("ok")
            return 1 if len(calls) == 1 else 0
    def popen(*a, **k):
        calls.append(a[0]); return Process(len(calls) - 1)
    monkeypatch.setattr(lp.subprocess, "Popen", popen)
    assert lp.download_audio("url", tmp_path).name == "source.webm"
    assert any("--cookies-from-browser" in call for call in calls[0])


def test_download_cookie_file_and_bad_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(lp.settings, "cookies_file", tmp_path / "cookies.txt")
    monkeypatch.setattr(lp.settings, "skip_browser_cookies", True)
    monkeypatch.setattr(lp.settings, "download_delay", 0)
    monkeypatch.setattr(lp, "fetch_metadata", lambda *a: {"duration": "unknown"})
    monkeypatch.setattr(lp, "_ytdlp_base_args", lambda: ["yt-dlp"])
    monkeypatch.setattr(lp, "_last_download_started", 0)
    calls = []
    class Process:
        stdout = iter(["[download] ???% done"])
        def wait(self): (tmp_path / "source.m4a").touch(); return 0
    monkeypatch.setattr(lp.subprocess, "Popen", lambda command, **kw: (calls.append(command) or Process()))
    assert lp.download_audio("url", tmp_path, lambda _: None).name == "source.m4a"
    assert "--cookies" in calls[0]


def test_download_respects_spacing(monkeypatch, tmp_path):
    monkeypatch.setattr(lp.settings, "cookies_file", None)
    monkeypatch.setattr(lp.settings, "skip_browser_cookies", True)
    monkeypatch.setattr(lp.settings, "download_delay", 3)
    monkeypatch.setattr(lp, "fetch_metadata", lambda *a: None)
    monkeypatch.setattr(lp, "_ytdlp_base_args", lambda: ["yt-dlp"])
    monkeypatch.setattr(lp, "_last_download_started", 9)
    times = iter([10.0, 10.0])
    sleeps = []
    monkeypatch.setattr(lp.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(lp.time, "sleep", sleeps.append)
    class Process:
        stdout = iter([])
        def wait(self): (tmp_path / "source.m4a").touch(); return 0
    monkeypatch.setattr(lp.subprocess, "Popen", lambda *a, **k: Process())
    lp.download_audio("url", tmp_path)
    assert sleeps == [2]


def test_find_and_clear_partial_downloads(tmp_path, monkeypatch):
    small = tmp_path / "source.webm"; small.write_text("a")
    big = tmp_path / "source.m4a"; big.write_text("larger")
    (tmp_path / "source.m4a.part").write_text("partial")
    assert lp._find_downloaded(tmp_path) == big
    original_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path.name == "source.webm": raise OSError("locked")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unlink)
    lp._clear_partial_downloads(tmp_path)
    assert small.exists()
    assert not big.exists()


def test_convert_probe_and_split_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(lp, "ffprobe_binary", lambda: "ffprobe")
    results = iter([SimpleNamespace(returncode=0, stdout="", stderr=""), SimpleNamespace(returncode=0, stdout="12.5", stderr=""), SimpleNamespace(returncode=0, stdout="", stderr="")])
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: next(results))
    assert lp.convert_to_wav(tmp_path / "in.mp3", tmp_path).name == "normalized-source.wav"
    assert lp.probe_duration(tmp_path / "in.mp3") == 12.5
    assert lp.split_audio_chunk(tmp_path / "in.wav", 2, 1, tmp_path / "nested/chunk.wav") == tmp_path / "nested/chunk.wav"


@pytest.mark.parametrize("stderr, expected", [("time=00:00:12.500", 12.5), ("time=01:02:03.000", 3723)])
def test_probe_duration_ffmpeg_fallback(monkeypatch, tmp_path, stderr, expected):
    monkeypatch.setattr(lp, "ffprobe_binary", lambda: None)
    monkeypatch.setattr(lp, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr=stderr))
    assert lp.probe_duration(tmp_path / "in") == expected


def test_probe_invalid_ffprobe_output_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "ffprobe_binary", lambda: "ffprobe")
    monkeypatch.setattr(lp, "ffmpeg_binary", lambda: "ffmpeg")
    results = iter([
        SimpleNamespace(returncode=0, stdout="not a number", stderr=""),
        SimpleNamespace(returncode=1, stdout="", stderr="time=00:00:09.000"),
    ])
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: next(results))
    assert lp.probe_duration(tmp_path / "in") == 9


def test_probe_duration_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "ffprobe_binary", lambda: "ffprobe")
    monkeypatch.setattr(lp, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="bad", stderr="no time"))
    with pytest.raises(RuntimeError, match="Could not determine"):
        lp.probe_duration(tmp_path / "in")
    results = iter([SimpleNamespace(returncode=1, stdout="bad", stderr=""), SimpleNamespace(returncode=0, stdout="", stderr="time=bad")])
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: next(results))
    with pytest.raises(ValueError):
        lp.probe_duration(tmp_path / "in")


def test_pick_vocals_output_prefers_vocal_and_work_alternative(tmp_path):
    vocal = tmp_path / "vocals.wav"; vocal.touch()
    assert lp._pick_vocals_output(["other.wav", str(vocal)], tmp_path) == vocal
    output_dir = tmp_path / "parent" / "out"; output_dir.mkdir(parents=True)
    work_dir = tmp_path / "parent" / "work"; work_dir.mkdir(); (work_dir / "stem.wav").touch()
    assert lp._pick_vocals_output(["nested/stem.wav"], output_dir) == work_dir / "stem.wav"
    assert lp._pick_vocals_output([], tmp_path) is None


def test_transcode_and_concat_cleanup(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    source = tmp_path / "source.wav"; source.touch()
    target = tmp_path / "out/vocals.mp3"
    assert lp.transcode_to_mp3(source, target) == target
    assert lp.concatenate_wav_chunks_to_mp3([source], target) == target
    assert not (target.parent / ".vocals-concat.txt").exists()
    with pytest.raises(ValueError): lp.concatenate_wav_chunks_to_mp3([], target)


def test_concat_list_removed_when_ffmpeg_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "ffmpeg")))
    with pytest.raises(subprocess.CalledProcessError):
        lp.concatenate_wav_chunks_to_mp3([tmp_path / "a'b.wav"], tmp_path / "out.mp3")
    assert not (tmp_path / ".out-concat.txt").exists()


def test_concat_cleanup_error_is_logged(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "ffmpeg_binary", lambda: "ffmpeg")
    monkeypatch.setattr(lp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    original_unlink = Path.unlink
    def unlink(path, *args, **kwargs):
        if path.name.endswith("-concat.txt"): raise OSError("busy")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", unlink)
    lp.concatenate_wav_chunks_to_mp3([tmp_path / "chunk.wav"], tmp_path / "out.mp3")


def _install_separator_fakes(monkeypatch, separator_cls):
    package = SimpleNamespace()
    separator_module = SimpleNamespace(Separator=separator_cls)
    package.separator = separator_module
    monkeypatch.setitem(sys.modules, "audio_separator", package)
    monkeypatch.setitem(sys.modules, "audio_separator.separator", separator_module)
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(__version__="test-version"))
    monkeypatch.setattr(lp, "_patch_librosa_get_duration", lambda: None)
    monkeypatch.setattr(lp, "seed_model_cache", lambda _: None)
    monkeypatch.setattr(lp.time, "sleep", lambda _: None)


def test_separate_vocals_success_and_unused_stem_cleanup(monkeypatch, tmp_path):
    vocals = tmp_path / "out" / "vocals.wav"
    other = tmp_path / "out" / "instrumental.wav"
    class Separator:
        def __init__(self, **kwargs): self.kwargs = kwargs
        def load_model(self, **kwargs): pass
        def separate(self, _: str): vocals.touch(); other.touch(); return ["instrumental.wav", "vocals.wav"]
    _install_separator_fakes(monkeypatch, Separator)
    monkeypatch.setattr(lp, "resolve_device", lambda _: ("cpu", ["CPUExecutionProvider"]))
    result = lp.separate_vocals(tmp_path / "source.wav", tmp_path / "out", tmp_path / "models")
    assert result["vocals"] == vocals.resolve()
    assert result["device"] == "cpu"
    assert not other.exists()


def test_separate_vocals_ignores_unused_stem_cleanup_error(monkeypatch, tmp_path):
    vocals = tmp_path / "out" / "vocals.wav"
    other = tmp_path / "out" / "other.wav"
    class Separator:
        def __init__(self, **kwargs): pass
        def load_model(self, **kwargs): pass
        def separate(self, _: str): vocals.touch(); other.touch(); return ["vocals.wav", "other.wav"]
    _install_separator_fakes(monkeypatch, Separator)
    monkeypatch.setattr(lp, "resolve_device", lambda _: ("cpu", ["CPUExecutionProvider"]))
    unlink = Path.unlink
    def fail_other(path, *args, **kwargs):
        if path == other: raise OSError("busy")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_other)
    assert lp.separate_vocals(tmp_path / "source", tmp_path / "out", tmp_path / "models")["vocals"] == vocals.resolve()


def test_patch_librosa_duration_compatibility(monkeypatch):
    from types import ModuleType
    calls = []
    def modern_duration(*, path=None): calls.append(path); return path
    module = ModuleType("librosa")
    module.get_duration = modern_duration
    monkeypatch.setitem(sys.modules, "librosa", module)
    lp._patch_librosa_get_duration()
    assert module.get_duration(filename="audio.wav") == "audio.wav"
    assert calls == ["audio.wav"]
    def old_duration(filename=None): return filename
    module.get_duration = old_duration
    lp._patch_librosa_get_duration()
    assert module.get_duration(filename="old.wav") == "old.wav"


def test_separate_vocals_repairs_corrupt_model_and_falls_back_cpu(monkeypatch, tmp_path):
    model = tmp_path / "models" / lp.DEFAULT_MODEL_NAME
    model.parent.mkdir(); model.write_text("corrupt")
    calls = []
    class Separator:
        def __init__(self, **kwargs): pass
        def load_model(self, **kwargs):
            calls.append("load")
            if len(calls) == 1: raise RuntimeError("invalid protobuf")
        def separate(self, _: str):
            vocal = tmp_path / "out" / "vocals.wav"; vocal.touch(); return [str(vocal)]
    _install_separator_fakes(monkeypatch, Separator)
    devices = iter([("nvidia-cuda", ["CUDAExecutionProvider", "CPUExecutionProvider"])])
    monkeypatch.setattr(lp, "resolve_device", lambda _: next(devices))
    result = lp.separate_vocals(tmp_path / "source", tmp_path / "out", model.parent, max_attempts=2)
    assert not model.exists()
    assert result["device"] == "cpu"
    assert calls == ["load", "load"]


def test_separate_vocals_errors_for_missing_output_and_exhaustion(monkeypatch, tmp_path):
    class Separator:
        def __init__(self, **kwargs): pass
        def load_model(self, **kwargs): pass
        def separate(self, _: str): return []
    _install_separator_fakes(monkeypatch, Separator)
    monkeypatch.setattr(lp, "resolve_device", lambda _: ("cpu", ["CPUExecutionProvider"]))
    with pytest.raises(RuntimeError, match="failed after 1 attempts"):
        lp.separate_vocals(tmp_path / "source", tmp_path / "out", tmp_path / "models", max_attempts=1)


def test_separate_vocals_handles_model_unlink_error(monkeypatch, tmp_path):
    model = tmp_path / "models" / lp.DEFAULT_MODEL_NAME
    model.parent.mkdir(); model.touch()
    class Separator:
        def __init__(self, **kwargs): pass
        def load_model(self, **kwargs): raise RuntimeError("corrupt model")
        def separate(self, _: str): return []
    _install_separator_fakes(monkeypatch, Separator)
    monkeypatch.setattr(lp, "resolve_device", lambda _: ("intel-openvino", ["OpenVINOExecutionProvider", "CPUExecutionProvider"]))
    unlink = Path.unlink
    def fail_model(path, *args, **kwargs):
        if path == model: raise OSError("read-only cache")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_model)
    with pytest.raises(RuntimeError):
        lp.separate_vocals(tmp_path / "source", tmp_path / "out", model.parent, max_attempts=1)
