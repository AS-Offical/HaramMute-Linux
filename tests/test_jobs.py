from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.jobs import Job, JobCapacityExceeded, JobStatus, JobStore


def make_job(
    job_id: str,
    *,
    url: str = "https://example.com/audio",
    owner: str = "user@example.com",
    status: JobStatus = JobStatus.queued,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        job_id=job_id,
        source_url=url,
        owner_email=owner,
        status=status,
        created_at=created_at or now,
        updated_at=updated_at or now,
    )


def test_job_round_trip_preserves_paths_status_and_chunks(tmp_path: Path) -> None:
    job = Job(
        job_id="a" * 32,
        source_url="https://example.com/audio",
        status=JobStatus.completed,
        result_path=tmp_path / "result.mp3",
        stems_files={"vocals": tmp_path / "vocals.mp3"},
        chunk_files={0: tmp_path / "chunk.wav"},
        chunks=[{"index": 0, "status": "completed", "file_ready": True}],
    )

    restored = Job.from_dict(job.to_dict())

    assert restored.status is JobStatus.completed
    assert restored.result_path == tmp_path / "result.mp3"
    assert restored.stems_files == {"vocals": tmp_path / "vocals.mp3"}
    assert restored.chunk_files == {0: tmp_path / "chunk.wav"}
    assert restored.all_chunks_completed()


def test_job_active_and_chunk_helpers() -> None:
    job = make_job("a" * 32, status=JobStatus.separating)
    job.chunks = [
        {"index": 0, "status": "completed", "file_ready": True},
        {"index": 1, "status": "completed", "file_ready": False},
    ]

    assert job.is_active
    assert job.get_completed_chunks_count() == 1
    assert not job.all_chunks_completed()


def test_store_persists_and_updates_known_fields(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job = make_job("b" * 32)

    store.create_job(job)
    updated = store.update_job(job.job_id, status=JobStatus.completed, progress=1.0)

    assert updated is not None
    assert store.get_job(job.job_id).status is JobStatus.completed
    assert updated.progress == 1.0
    with pytest.raises(KeyError, match="Unknown job field"):
        store.update_job(job.job_id, missing_field=True)


def test_store_rejects_invalid_ids_and_ignores_missing_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)

    with pytest.raises(ValueError, match="32-character lowercase UUID hex"):
        store.create_job(make_job("not-a-uuid"))
    assert store.get_job("missing") is None
    assert store.update_job("missing", status=JobStatus.failed) is None
    assert store.update_chunk("missing", 0, status="failed") is None


def test_active_job_lookup_normalizes_url_and_owner(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    store.create_job(make_job("c" * 32, url="HTTPS://Example.com/audio", owner="User@Example.com"))

    found = store.find_active_job(" https://example.com/audio ", 2, "user@example.com")

    assert found is not None
    assert found.job_id == "c" * 32


def test_active_job_creation_reuses_matching_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    existing = make_job("d" * 32)
    store.create_job(existing)
    replacement = make_job("e" * 32)

    selected, created = store.create_or_reuse_active_job(replacement)

    assert selected.job_id == existing.job_id
    assert created is False


def test_cached_job_lookup_returns_newest_completed_result(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    now = datetime.now(timezone.utc)
    store.create_job(make_job("f" * 32, status=JobStatus.completed, updated_at=now - timedelta(hours=1)))
    store.create_job(make_job("1" * 32, status=JobStatus.completed, updated_at=now))

    cached = store.find_cached_job("https://example.com/audio", 2, "user@example.com")

    assert cached is not None
    assert cached.job_id == "1" * 32


def test_admission_enforces_queue_limit_and_can_reuse(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    first = make_job("2" * 32)
    assert store.admit_local_job(first, max_queued=1) == (first, True)

    duplicate, created = store.admit_local_job(make_job("3" * 32), max_queued=1)
    assert duplicate.job_id == first.job_id
    assert created is False

    with pytest.raises(JobCapacityExceeded) as error:
        store.admit_local_job(make_job("4" * 32, url="https://example.com/other"), max_queued=1)
    assert error.value.limit_kind == "queued"


def test_recovery_fails_interrupted_work_and_returns_queued_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    queued = make_job("5" * 32)
    interrupted = make_job("6" * 32, status=JobStatus.separating)
    store.create_job(queued)
    store.create_job(interrupted)

    recovered = store.recover_interrupted_local_jobs()
    failed = store.get_job(interrupted.job_id)

    assert [item.job_id for item in recovered] == [queued.job_id]
    assert failed.status is JobStatus.failed
    assert failed.failure_code == "desktop_runtime_interrupted"
    assert failed.failure_recoverable is True


def test_expired_job_ids_only_include_old_terminal_jobs(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    store._write(make_job("7" * 32, status=JobStatus.failed, updated_at=cutoff - timedelta(seconds=1)))
    store._write(make_job("8" * 32, status=JobStatus.queued, updated_at=cutoff - timedelta(days=2)))
    store._write(make_job("9" * 32, status=JobStatus.completed, updated_at=cutoff + timedelta(seconds=1)))

    assert store.expired_job_ids(cutoff) == ["7" * 32]


def test_invalid_persisted_json_is_ignored(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    broken_id = "a" * 32
    job_file = store.job_dir(broken_id) / "job.json"
    job_file.parent.mkdir(parents=True)
    job_file.write_text("{broken", encoding="utf-8")

    assert store.get_job(broken_id) is None
    assert store._iter_jobs() == []
