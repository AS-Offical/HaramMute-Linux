import importlib
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.jobs import Job, JobStatus
from app.schemas import (
    ChunkInfo,
    ChunkStatus,
    JobCreateRequest,
    JobResultResponse,
    JobStatusResponse,
    UpdateInfo,
)


def test_limits_are_defined_for_local_queue() -> None:
    from app import limits

    assert limits.JOBS_RATE_LIMIT_PER_HOUR == 20
    assert limits.MAX_CONCURRENT_JOBS == 5
    assert limits.MAX_QUEUED_JOBS == 10
    assert limits.MAX_VIDEO_MINUTES == 90
    assert limits.MAX_VIDEO_SECONDS == 5400


def test_settings_accept_overrides_and_use_data_directory(tmp_path) -> None:
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        local_mode=False,
        encoding_quality=7,
        data_dir=tmp_path,
    )

    assert settings.local_mode is False
    assert settings.encoding_quality == 7
    assert settings.data_dir == tmp_path


def test_settings_module_initializes_runtime_directories_and_cpu_flag(monkeypatch, tmp_path) -> None:
    import app.config as config

    monkeypatch.setenv("MUSIC_REMOVER_FORCE_CPU", "true")
    monkeypatch.setenv("HARAMMUTE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MUSIC_REMOVER_COOKIES_FILE", raising=False)
    try:
        config = importlib.reload(config)
        assert config.settings.force_cpu is True
        assert config.settings.data_dir == tmp_path
        assert (tmp_path / "jobs").is_dir()
        assert config.os.environ["CUDA_VISIBLE_DEVICES"] == ""
    finally:
        monkeypatch.delenv("MUSIC_REMOVER_FORCE_CPU", raising=False)
        monkeypatch.delenv("HARAMMUTE_DATA_DIR", raising=False)
        importlib.reload(config)


def test_settings_reject_missing_configured_cookie_file(monkeypatch, tmp_path) -> None:
    import app.config as config

    cookie_file = tmp_path / "missing-cookies.txt"
    monkeypatch.setenv("MUSIC_REMOVER_COOKIES_FILE", str(cookie_file))
    try:
        with pytest.raises(FileNotFoundError, match="Configured cookies file"):
            importlib.reload(config)
    finally:
        monkeypatch.delenv("MUSIC_REMOVER_COOKIES_FILE", raising=False)
        importlib.reload(config)


def test_job_create_request_validates_url_and_fixed_stem_count() -> None:
    assert str(JobCreateRequest(url="https://example.com/audio").url) == "https://example.com/audio"
    with pytest.raises(ValidationError):
        JobCreateRequest(url="https://example.com/audio", stems=4)


def test_chunk_and_update_models() -> None:
    chunk = ChunkInfo(index=0, status=ChunkStatus.completed, start_time=0, end_time=2, duration=2)
    update = UpdateInfo(version="1.2.3", download_url="https://example.com/release")

    assert chunk.file_ready is False
    assert chunk.status is ChunkStatus.completed
    assert update.severity == "minor"
    assert update.download_url == "https://example.com/release"


def make_schema_job(**overrides) -> Job:
    now = datetime.now(timezone.utc)
    values = {
        "job_id": "a" * 32,
        "source_url": "https://example.com/audio",
        "status": JobStatus.failed,
        "created_at": now,
        "updated_at": now,
        "error_detail": "Local worker could not start",
        "chunks": [
            {"index": 0, "status": "completed", "progress": 1, "start_time": 0,
             "end_time": 60, "duration": 60, "file_ready": True},
            {"index": 2, "status": "pending", "start_time": 120, "end_time": 180,
             "duration": 60, "file_ready": True},
        ],
    }
    values.update(overrides)
    return Job(**values)


def test_status_response_counts_only_contiguous_ready_chunks(monkeypatch) -> None:
    monkeypatch.delenv("HARAMMUTE_UPDATE_VERSION", raising=False)
    response = JobStatusResponse.from_job(make_schema_job())

    assert response.total_chunks == 2
    assert response.chunks_completed == 1
    assert response.failure_code == "desktop_runtime_failed"
    assert response.update is None


def test_status_response_uses_explicit_failure_code_and_update_env(monkeypatch) -> None:
    monkeypatch.setenv("HARAMMUTE_UPDATE_VERSION", "1.2.0")
    monkeypatch.setenv("HARAMMUTE_UPDATE_SEVERITY", "major")
    monkeypatch.setenv("HARAMMUTE_UPDATE_MESSAGE", "Update available")
    monkeypatch.setenv("HARAMMUTE_UPDATE_DOWNLOAD_URL", "https://example.com/update")
    response = JobStatusResponse.from_job(
        make_schema_job(failure_code="worker_down", error_detail="local worker could not start")
    )

    assert response.failure_code == "worker_down"
    assert response.update.version == "1.2.0"
    assert response.update.severity == "major"
    assert response.update.message == "Update available"
    assert str(response.update.download_url) == "https://example.com/update"


def test_result_response_adds_download_metadata(monkeypatch) -> None:
    monkeypatch.delenv("HARAMMUTE_UPDATE_VERSION", raising=False)
    response = JobResultResponse.from_job(
        make_schema_job(chunks=[]),
        download_url="https://example.com/result",
        preview_url=None,
        stems=["vocals"],
    )

    assert response.download_url == "https://example.com/result"
    assert response.preview_url is None
    assert response.available_stems == ["vocals"]
    assert response.chunks_completed == 0
