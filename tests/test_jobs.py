from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

import pytest

from app import jobs as jobs_module
from app.jobs import (
    Job,
    JobCapacityExceeded,
    JobStatus,
    JobStore,
    _deserialize_path_map,
    _serialize,
)


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


def test_serializers_handle_enums_and_invalid_path_maps(tmp_path: Path) -> None:
    class Example(Enum):
        ready = "ready"

    assert _serialize(Example.ready) == "ready"
    assert _serialize(object()) is not None
    assert _deserialize_path_map(None) == {}
    assert _deserialize_path_map({"vocals": str(tmp_path / "vocals.wav")}) == {
        "vocals": tmp_path / "vocals.wav"
    }


def test_job_from_dict_handles_missing_and_malformed_dates() -> None:
    minimal = Job.from_dict({"job_id": "a" * 32})
    malformed = Job.from_dict(
        {"job_id": "b" * 32, "created_at": "not-a-date", "updated_at": "2025-01-02T03:04:05"}
    )

    assert minimal.source_url == ""
    assert minimal.stems == 2
    assert malformed.created_at is not None
    assert malformed.updated_at.tzinfo is timezone.utc


def test_store_uses_environment_data_directory_and_generates_uuid(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MUSIC_REMOVER_DATA_DIR", str(tmp_path))
    store = JobStore()

    assert store.root == tmp_path / "jobs"
    assert len(store.new_job_id()) == 32


def test_update_chunk_updates_matching_entry_and_leaves_missing_entry(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job = make_job("a" * 32)
    job.chunks = [{"index": 1, "status": "pending"}]
    store.create_job(job)

    updated = store.update_chunk(job.job_id, 1, status="completed", file_ready=True)
    unchanged = store.update_chunk(job.job_id, 9, status="completed")

    assert updated.chunks[0]["status"] == "completed"
    assert unchanged.chunks == updated.chunks


def test_iter_jobs_skips_files_and_returns_empty_if_root_unreadable(tmp_path: Path, monkeypatch) -> None:
    store = JobStore(tmp_path)
    (store.root / "not-a-directory").write_text("ignored", encoding="utf-8")
    assert store._iter_jobs() == []

    original_iterdir = Path.iterdir

    def fail_for_store_root(path):
        if path == store.root:
            raise OSError("denied")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_for_store_root)
    assert store._iter_jobs() == []


def test_lookups_return_none_without_a_match_and_creation_adds_new_job(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    assert store.find_active_job("https://example.com", 2, "nobody") is None
    assert store.find_cached_job("https://example.com", 2, "nobody") is None
    created, did_create = store.create_or_reuse_active_job(make_job("b" * 32))
    assert did_create is True
    assert created.job_id == "b" * 32


def test_count_cleanup_and_terminal_expiration(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    cutoff = datetime.now(timezone.utc)
    old = make_job("c" * 32, status=JobStatus.failed, updated_at=cutoff - timedelta(seconds=5))
    active = make_job("d" * 32, owner="OTHER@example.com", status=JobStatus.separating)
    store._write(old)
    store._write(active)

    assert store.count_jobs_by_owner("user@example.com", {"failed", JobStatus.queued}) == 1
    assert store.cleanup(cutoff) == 1
    assert store.expired_job_ids(cutoff) == [old.job_id]


def test_recovery_keeps_terminal_jobs_unchanged(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    completed = make_job("e" * 32, status=JobStatus.completed)
    failed = make_job("f" * 32, status=JobStatus.failed)
    store.create_job(completed)
    store.create_job(failed)

    assert store.recover_interrupted_local_jobs() == []
    assert store.get_job(completed.job_id).status is JobStatus.completed
    assert store.get_job(failed.job_id).status is JobStatus.failed


@pytest.mark.parametrize("unlink_fails", [False, True])
def test_store_write_cleans_temporary_file_after_replace_failure(
    monkeypatch, tmp_path: Path, unlink_fails: bool
) -> None:
    store = JobStore(tmp_path)

    def fail_replace(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr(jobs_module.os, "replace", fail_replace)
    if unlink_fails:
        monkeypatch.setattr(jobs_module.os, "unlink", lambda *_args: (_ for _ in ()).throw(OSError("unlink failed")))

    with pytest.raises(OSError, match="replace failed"):
        store._write(make_job("0" * 32))


def test_store_skips_structurally_invalid_json_records(tmp_path: Path) -> None:
    store = JobStore(tmp_path)
    job_id = "1" * 32
    job_file = store.job_dir(job_id) / "job.json"
    job_file.parent.mkdir(parents=True)
    job_file.write_text("{}", encoding="utf-8")

    assert store.get_job(job_id) is None
