"""Job model and persistent job store for HaramMute (Linux build).

Reimplemented pure-Python replacement for the compiled Windows module.
Each job is persisted as JSON inside its own directory under
``{data_dir}/jobs/{job_id}/job.json`` so the cleanup logic in
``app.main`` (which removes whole job directories by mtime) works
unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("app.jobs")

ACTIVE_STATUSES = {"queued", "downloading", "separating", "packaging"}


class JobCapacityExceeded(RuntimeError):
    """Raised when the local job queue reaches its configured capacity."""

    def __init__(self, limit_kind: str, limit: int) -> None:
        self.limit_kind = limit_kind
        self.limit = limit
        super().__init__(f"{limit_kind} job limit reached ({limit})")


class JobStatus(str, Enum):
    queued = "queued"
    downloading = "downloading"
    separating = "separating"
    packaging = "packaging"
    completed = "completed"
    failed = "failed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _deserialize_path_map(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {k: Path(v) for k, v in raw.items()}


class Job:
    """A single music-removal job."""

    def __init__(
        self,
        job_id: str,
        source_url: str,
        stems: int = 2,
        owner_email: str = "",
        status: JobStatus | str = JobStatus.queued,
        message: Optional[str] = None,
        progress: Optional[float] = 0.0,
        error_detail: Optional[str] = None,
        failure_stage: Optional[str] = None,
        failure_code: Optional[str] = None,
        failure_recoverable: Optional[bool] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        result_path: Optional[Path] = None,
        stems_files: Optional[dict[str, Path]] = None,
        chunking_enabled: bool = False,
        total_duration: Optional[float] = None,
        chunk_duration: float = 60.0,
        chunks: Optional[list[dict]] = None,
        chunk_files: Optional[dict[int, Path]] = None,
        processing_stats: Optional[dict] = None,
    ) -> None:
        self.job_id = job_id
        self.source_url = source_url
        self.stems = stems
        self.owner_email = owner_email or ""
        self.status = JobStatus(status)
        self.message = message
        self.progress = progress
        self.error_detail = error_detail
        self.failure_stage = failure_stage
        self.failure_code = failure_code
        self.failure_recoverable = failure_recoverable
        self.created_at = created_at or _utcnow()
        self.updated_at = updated_at or self.created_at
        self.result_path = result_path
        self.stems_files = stems_files or {}
        self.chunking_enabled = chunking_enabled
        self.total_duration = total_duration
        self.chunk_duration = chunk_duration
        self.chunks = chunks or []
        self.chunk_files = chunk_files or {}
        self.processing_stats = processing_stats or {}

    # -- serialization ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "source_url": self.source_url,
            "stems": self.stems,
            "owner_email": self.owner_email,
            "status": self.status.value,
            "message": self.message,
            "progress": self.progress,
            "error_detail": self.error_detail,
            "failure_stage": self.failure_stage,
            "failure_code": self.failure_code,
            "failure_recoverable": self.failure_recoverable,
            "created_at": _serialize(self.created_at),
            "updated_at": _serialize(self.updated_at),
            "result_path": _serialize(self.result_path),
            "stems_files": _serialize(self.stems_files),
            "chunking_enabled": self.chunking_enabled,
            "total_duration": self.total_duration,
            "chunk_duration": self.chunk_duration,
            "chunks": _serialize(self.chunks),
            "chunk_files": _serialize(self.chunk_files),
            "processing_stats": self.processing_stats,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        def _dt(value: Any) -> Optional[datetime]:
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed

        return cls(
            job_id=data["job_id"],
            source_url=data.get("source_url", ""),
            stems=int(data.get("stems", 2)),
            owner_email=data.get("owner_email", ""),
            status=data.get("status", JobStatus.queued),
            message=data.get("message"),
            progress=data.get("progress", 0.0),
            error_detail=data.get("error_detail"),
            failure_stage=data.get("failure_stage"),
            failure_code=data.get("failure_code"),
            failure_recoverable=data.get("failure_recoverable"),
            created_at=_dt(data.get("created_at")),
            updated_at=_dt(data.get("updated_at")),
            result_path=Path(data["result_path"]) if data.get("result_path") else None,
            stems_files=_deserialize_path_map(data.get("stems_files")),
            chunking_enabled=bool(data.get("chunking_enabled", False)),
            total_duration=data.get("total_duration"),
            chunk_duration=float(data.get("chunk_duration", 60.0)),
            chunks=list(data.get("chunks") or []),
            chunk_files={int(k): Path(v) for k, v in (data.get("chunk_files") or {}).items()},
            processing_stats=dict(data.get("processing_stats") or {}),
        )

    # -- helpers used by schemas/main --------------------------------------
    @property
    def is_active(self) -> bool:
        return self.status.value in ACTIVE_STATUSES

    def get_completed_chunks_count(self) -> int:
        """Count only contiguous ready chunks from index 0."""
        count = 0
        ready_by_index = {
            chunk.get("index"): bool(chunk.get("file_ready")) and chunk.get("status") == "completed"
            for chunk in self.chunks
        }
        while ready_by_index.get(count, False):
            count += 1
        return count

    def all_chunks_completed(self) -> bool:
        return bool(self.chunks) and all(
            chunk.get("status") == "completed" and chunk.get("file_ready") for chunk in self.chunks
        )


class JobStore:
    """Thread-safe JSON-file-backed store rooted at ``{data_dir}/jobs``."""

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        if data_dir is None:
            data_dir = Path(os.environ.get("MUSIC_REMOVER_DATA_DIR", "server_data"))
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # -- paths --------------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def _job_file(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            return self.root / ".invalid-job-id" / "job.json"
        return self.job_dir(job_id) / "job.json"

    # -- persistence ---------------------------------------------------------
    def _write(self, job: Job) -> None:
        directory = self.job_dir(job.job_id)
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(job.to_dict(), ensure_ascii=False, indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix=".job-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(tmp_name, self._job_file(job.job_id))
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _read(self, job_id: str) -> Optional[Job]:
        path = self._job_file(job_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return Job.from_dict(data)
        except (KeyError, TypeError, ValueError):
            logger.warning("Corrupt job record skipped: %s", job_id)
            return None

    # -- CRUD -----------------------------------------------------------------
    def create_job(self, job: Job) -> Job:
        if not re.fullmatch(r"[0-9a-f]{32}", job.job_id):
            raise ValueError("Job ID must be a 32-character lowercase UUID hex string")
        with self._lock:
            job.created_at = job.created_at or _utcnow()
            job.updated_at = _utcnow()
            self._write(job)
        return job

    def new_job_id(self) -> str:
        return uuid.uuid4().hex

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._read(job_id)

    def update_job(self, job_id: str, **fields: Any) -> Optional[Job]:
        with self._lock:
            job = self._read(job_id)
            if job is None:
                return None
            for key, value in fields.items():
                if hasattr(job, key):
                    setattr(job, key, value)
                else:
                    raise KeyError(f"Unknown job field: {key}")
            job.updated_at = _utcnow()
            self._write(job)
            return job

    def update_chunk(self, job_id: str, index: int, **fields: Any) -> Optional[Job]:
        """Update a specific chunk's status entry by index."""
        with self._lock:
            job = self._read(job_id)
            if job is None:
                return None
            for chunk in job.chunks:
                if int(chunk.get("index", -1)) == int(index):
                    chunk.update(fields)
                    break
            else:
                logger.warning("update_chunk: chunk %s not found in job %s", index, job_id)
                return job
            job.updated_at = _utcnow()
            self._write(job)
            return job

    # -- lookups ---------------------------------------------------------------
    def _iter_jobs(self) -> list[Job]:
        jobs: list[Job] = []
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return jobs
        for entry in entries:
            if not entry.is_dir():
                continue
            job = self._read(entry.name)
            if job is not None:
                jobs.append(job)
        return jobs

    @staticmethod
    def _normalize_url(url: str) -> str:
        return str(url).strip().lower()

    def find_active_job(self, url: str, stems: int, owner_email: str) -> Optional[Job]:
        target = self._normalize_url(url)
        with self._lock:
            candidates = [
                job
                for job in self._iter_jobs()
                if job.is_active
                and self._normalize_url(job.source_url) == target
                and job.stems == stems
                and (job.owner_email or "").lower() == (owner_email or "").lower()
            ]
        if not candidates:
            return None
        candidates.sort(key=lambda job: job.created_at, reverse=True)
        return candidates[0]

    def find_cached_job(self, url: str, stems: int, owner_email: str) -> Optional[Job]:
        target = self._normalize_url(url)
        with self._lock:
            candidates = [
                job
                for job in self._iter_jobs()
                if job.status == JobStatus.completed
                and self._normalize_url(job.source_url) == target
                and job.stems == stems
                and (job.owner_email or "").lower() == (owner_email or "").lower()
            ]
        if not candidates:
            return None
        candidates.sort(key=lambda job: job.updated_at, reverse=True)
        return candidates[0]

    def create_or_reuse_active_job(self, job: Job) -> tuple[Job, bool]:
        """Atomically reuse a matching active job or create the supplied job."""
        with self._lock:
            existing = self.find_active_job(job.source_url, job.stems, job.owner_email)
            if existing is not None:
                return existing, False
            self.create_job(job)
            return job, True

    def admit_local_job(
        self,
        job: Job,
        *,
        max_queued: int,
        reuse_active: bool = True,
    ) -> tuple[Job, bool]:
        """Atomically enforce local queue limits and persist a new job."""
        with self._lock:
            if reuse_active:
                existing = self.find_active_job(job.source_url, job.stems, job.owner_email)
                if existing is not None:
                    return existing, False

            owner = (job.owner_email or "").lower()
            owned = [
                item for item in self._iter_jobs()
                if (item.owner_email or "").lower() == owner
            ]
            queued = sum(item.status == JobStatus.queued for item in owned)
            if queued >= max_queued:
                raise JobCapacityExceeded("queued", max_queued)

            self.create_job(job)
            return job, True

    def count_jobs_by_owner(self, email: str, statuses: set) -> int:
        wanted = {JobStatus(status) if not isinstance(status, JobStatus) else status for status in statuses}
        with self._lock:
            return sum(
                1
                for job in self._iter_jobs()
                if (job.owner_email or "").lower() == (email or "").lower() and job.status in wanted
            )

    def recover_interrupted_local_jobs(self) -> list[Job]:
        """Fail stale in-progress work and return persisted queued work."""
        queued_jobs = []
        with self._lock:
            for job in self._iter_jobs():
                if job.status == JobStatus.queued:
                    queued_jobs.append(job)
                elif job.status in {
                    JobStatus.downloading,
                    JobStatus.separating,
                    JobStatus.packaging,
                }:
                    job.status = JobStatus.failed
                    job.message = "Processing stopped when HaramMute closed"
                    job.error_detail = "The previous local worker was interrupted; retry this job."
                    job.failure_stage = "desktop_runtime"
                    job.failure_code = "desktop_runtime_interrupted"
                    job.failure_recoverable = True
                    job.updated_at = _utcnow()
                    self._write(job)
        return queued_jobs

    def cleanup(self, cutoff: datetime) -> int:
        """Delete job records whose last update predates the cutoff.

        Directory removal itself is handled by app.main; this only drops
        records for directories that no longer exist.
        """
        removed = 0
        with self._lock:
            for job in self._iter_jobs():
                if job.updated_at < cutoff:
                    removed += 1
        return removed

    def expired_job_ids(self, cutoff: datetime) -> list[str]:
        """List terminal jobs older than the retention window."""
        with self._lock:
            return [
                job.job_id
                for job in self._iter_jobs()
                if job.status in {JobStatus.completed, JobStatus.failed}
                and job.updated_at < cutoff
            ]
