from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import pipeline
from app.jobs import JobStatus


class Store:
    def __init__(self, job=None):
        self.job = job
        self.updates = []
        self.chunk_updates = []

    def get_job(self, job_id):
        return self.job

    def update_job(self, job_id, **fields):
        self.updates.append(fields)
        if self.job:
            for key, value in fields.items():
                setattr(self.job, key, value)
        return self.job

    def update_chunk(self, job_id, index, **fields):
        self.chunk_updates.append((index, fields))
        if self.job and getattr(self.job, "chunks", None):
            for chunk in self.job.chunks:
                if chunk["index"] == index:
                    chunk.update(fields)
        return self.job


def job(job_id="a" * 32, duration=10, chunk_duration=60):
    return SimpleNamespace(
        job_id=job_id, source_url="https://example.com", stems=2,
        chunk_duration=chunk_duration, chunks=[],
    )


def mock_single_pipeline(monkeypatch, tmp_path, duration=10):
    monkeypatch.setattr(pipeline.settings, "data_dir", tmp_path)
    source = tmp_path / "source.m4a"; source.touch()
    wav = tmp_path / "source.wav"; wav.touch()
    vocal = tmp_path / "vocal.wav"; vocal.touch()
    mp3 = tmp_path / "vocals.mp3"
    monkeypatch.setattr(pipeline.lp, "download_audio", lambda *a, **k: source)
    monkeypatch.setattr(pipeline.lp, "convert_to_wav", lambda *a: wav)
    monkeypatch.setattr(pipeline.lp, "probe_duration", lambda *a: duration)
    monkeypatch.setattr(pipeline.lp, "separate_vocals", lambda *a, **k: {"vocals": vocal, "seconds": 2.5, "device": "cpu", "providers": ["CPUExecutionProvider"]})
    monkeypatch.setattr(pipeline.lp, "transcode_to_mp3", lambda _src, target, **kw: (target.parent.mkdir(parents=True, exist_ok=True), target.touch(), target)[-1])
    return source, wav, vocal, mp3


def test_missing_job_is_skipped(caplog):
    pipeline.process_job("missing", Store())
    assert "not found" in caplog.text


def test_process_single_file_completes(monkeypatch, tmp_path):
    current = job()
    store = Store(current)
    mock_single_pipeline(monkeypatch, tmp_path)
    pipeline.process_job(current.job_id, store)
    assert current.status is JobStatus.completed
    assert current.processing_stats["mode"] == "single"
    assert current.processing_stats["execution_device"] == "cpu"
    assert current.progress == 1.0


def test_process_download_progress_callback(monkeypatch, tmp_path):
    current = job(); store = Store(current)
    monkeypatch.setattr(pipeline.settings, "data_dir", tmp_path)
    source = tmp_path / "source.m4a"; source.touch()
    wav = tmp_path / "source.wav"; wav.touch()
    observed = []
    def download(url, work, progress_callback, delay_between_attempts):
        progress_callback(0.5)
        return source
    monkeypatch.setattr(pipeline.lp, "download_audio", download)
    monkeypatch.setattr(pipeline.lp, "convert_to_wav", lambda *a: wav)
    monkeypatch.setattr(pipeline.lp, "probe_duration", lambda *a: 5)
    monkeypatch.setattr(pipeline.lp, "separate_vocals", lambda *a, **k: {"vocals": tmp_path / "v.wav", "seconds": 1})
    monkeypatch.setattr(pipeline.lp, "transcode_to_mp3", lambda src, target, **kw: target)
    monkeypatch.setattr(pipeline, "_safe_update", lambda st, jid, **fields: (observed.append(fields), st.update_job(jid, **fields)))
    pipeline.process_job(current.job_id, store)
    assert any(fields.get("progress") == 0.085 for fields in observed)


def test_process_rejects_overlong_media(monkeypatch, tmp_path):
    current = job(); store = Store(current)
    mock_single_pipeline(monkeypatch, tmp_path, pipeline.MAX_VIDEO_SECONDS + 1)
    pipeline.process_job(current.job_id, store)
    assert current.status is JobStatus.failed
    assert current.failure_stage == "validation"
    assert "90-minute" in current.error_detail


def test_process_download_failure_is_recorded(monkeypatch, tmp_path):
    current = job(); store = Store(current)
    monkeypatch.setattr(pipeline.settings, "data_dir", tmp_path)
    monkeypatch.setattr(pipeline.lp, "download_audio", lambda *a, **k: (_ for _ in ()).throw(OSError("network")))
    pipeline.process_job(current.job_id, store)
    assert current.status is JobStatus.failed
    assert current.failure_code == "download_failed"


def test_safe_update_never_raises(caplog):
    caplog.set_level("DEBUG", logger="app.pipeline")
    class Broken:
        def update_job(self, *args, **kwargs): raise RuntimeError("disk full")
    pipeline._safe_update(Broken(), "job", progress=1)
    assert "Status update failed" in caplog.text


def test_chunked_job_completes_and_assembles(monkeypatch, tmp_path):
    current = job(chunk_duration=60); store = Store(current)
    monkeypatch.setattr(pipeline.settings, "data_dir", tmp_path)
    source = tmp_path / "source.m4a"; source.touch()
    wav = tmp_path / "source.wav"; wav.touch()
    monkeypatch.setattr(pipeline.lp, "download_audio", lambda *a, **k: source)
    monkeypatch.setattr(pipeline.lp, "convert_to_wav", lambda *a: wav)
    monkeypatch.setattr(pipeline.lp, "probe_duration", lambda *a: 130)
    def split(_wav, start, end, output): output.parent.mkdir(parents=True, exist_ok=True); output.touch(); return output
    monkeypatch.setattr(pipeline.lp, "split_audio_chunk", split)
    def separate(chunk, output_dir, **kwargs):
        vocal = output_dir / f"{chunk.stem}-vocals.wav"; vocal.parent.mkdir(parents=True, exist_ok=True); vocal.touch()
        return {"vocals": vocal, "seconds": 1, "device": "cpu", "providers": ["CPUExecutionProvider"]}
    monkeypatch.setattr(pipeline.lp, "separate_vocals", separate)
    monkeypatch.setattr(pipeline.lp, "transcode_to_mp3", lambda src, target, **kw: (target.touch(), target)[-1])
    monkeypatch.setattr(pipeline.lp, "concatenate_wav_chunks_to_mp3", lambda chunks, target, **kw: (target.touch(), target)[-1])
    pipeline.process_job(current.job_id, store)
    assert current.status is JobStatus.completed
    assert current.processing_stats["mode"] == "chunked"
    assert current.processing_stats["assembled_vocals"] is True
    assert current.total_chunks == 3
    assert all(c["status"] == "completed" for c in current.chunks)


def test_chunk_failure_marks_chunk_then_fails_job(monkeypatch, tmp_path):
    current = job(chunk_duration=60); store = Store(current)
    monkeypatch.setattr(pipeline.settings, "data_dir", tmp_path)
    source = tmp_path / "source"; source.touch()
    wav = tmp_path / "wav"; wav.touch()
    monkeypatch.setattr(pipeline.lp, "download_audio", lambda *a, **k: source)
    monkeypatch.setattr(pipeline.lp, "convert_to_wav", lambda *a: wav)
    monkeypatch.setattr(pipeline.lp, "probe_duration", lambda *a: 130)
    monkeypatch.setattr(pipeline.lp, "split_audio_chunk", lambda *a: (_ for _ in ()).throw(OSError("split error")))
    pipeline.process_job(current.job_id, store)
    assert current.status is JobStatus.failed
    assert current.failure_stage == "chunk_0_split"
    assert any(fields.get("status") == "failed" for _, fields in store.chunk_updates)


def test_chunk_pipeline_continues_progress_using_store_state(monkeypatch, tmp_path):
    current = job(chunk_duration=60); store = Store(current)
    monkeypatch.setattr(pipeline.settings, "data_dir", tmp_path)
    source = tmp_path / "source"; source.touch(); wav = tmp_path / "wav"; wav.touch()
    monkeypatch.setattr(pipeline.lp, "download_audio", lambda *a, **k: source)
    monkeypatch.setattr(pipeline.lp, "convert_to_wav", lambda *a: wav)
    monkeypatch.setattr(pipeline.lp, "probe_duration", lambda *a: 121)
    def split(_wav, start, end, out): out.parent.mkdir(parents=True, exist_ok=True); out.touch(); return out
    monkeypatch.setattr(pipeline.lp, "split_audio_chunk", split)
    def separate(chunk, output_dir, **kw):
        vocal = output_dir / f"{chunk.stem}-vocals.wav"; vocal.parent.mkdir(parents=True, exist_ok=True); vocal.touch(); return {"vocals": vocal, "seconds": 1}
    monkeypatch.setattr(pipeline.lp, "separate_vocals", separate)
    monkeypatch.setattr(pipeline.lp, "transcode_to_mp3", lambda _s, t, **kw: (t.touch(), t)[-1])
    monkeypatch.setattr(pipeline.lp, "concatenate_wav_chunks_to_mp3", lambda _c, t, **kw: (t.touch(), t)[-1])
    pipeline.process_job(current.job_id, store)
    progress_values = [item.get("progress") for item in store.updates if "progress" in item]
    assert any(value and value > 0.89 for value in progress_values)


def test_chunk_progress_falls_back_when_job_disappears(monkeypatch, tmp_path):
    current = job(chunk_duration=60)
    class DisappearingStore(Store):
        calls = 0
        def get_job(self, job_id):
            self.calls += 1
            return self.job if self.calls == 1 else None
    store = DisappearingStore(current)
    monkeypatch.setattr(pipeline.settings, "data_dir", tmp_path)
    source = tmp_path / "source"; source.touch(); wav = tmp_path / "wav"; wav.touch()
    monkeypatch.setattr(pipeline.lp, "download_audio", lambda *a, **k: source)
    monkeypatch.setattr(pipeline.lp, "convert_to_wav", lambda *a: wav)
    monkeypatch.setattr(pipeline.lp, "probe_duration", lambda *a: 121)
    def split(_wav, start, end, out): out.parent.mkdir(parents=True, exist_ok=True); out.touch(); return out
    monkeypatch.setattr(pipeline.lp, "split_audio_chunk", split)
    def separate(chunk, output_dir, **kw):
        vocal = output_dir / f"{chunk.stem}-vocals.wav"; vocal.parent.mkdir(parents=True, exist_ok=True); vocal.touch(); return {"vocals": vocal, "seconds": 1}
    monkeypatch.setattr(pipeline.lp, "separate_vocals", separate)
    monkeypatch.setattr(pipeline.lp, "transcode_to_mp3", lambda _s, t, **kw: (t.touch(), t)[-1])
    monkeypatch.setattr(pipeline.lp, "concatenate_wav_chunks_to_mp3", lambda _c, t, **kw: (t.touch(), t)[-1])
    original_unlink = Path.unlink
    def fail_vocal_cleanup(path, *args, **kwargs):
        if path.name.endswith("-vocals.wav"):
            raise OSError("busy")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_vocal_cleanup)
    pipeline.process_job(current.job_id, store)
    assert current.status is JobStatus.completed


def test_encode_chunk_vocals_ignores_unlink_error(monkeypatch, tmp_path):
    source = tmp_path / "vocal.wav"; source.touch()
    monkeypatch.setattr(pipeline.lp, "transcode_to_mp3", lambda _s, target, **kw: target)
    original = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda path, *a, **k: (_ for _ in ()).throw(OSError("busy")) if path == source else original(path, *a, **k))
    assert pipeline._encode_chunk_vocals(source, tmp_path, "v.mp3") == tmp_path / "v.mp3"
