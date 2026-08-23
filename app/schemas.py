import os
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

from .jobs import Job, JobStatus


class UpdateInfo(BaseModel):
    version: str
    severity: str = "minor"
    message: str = ""
    download_url: Optional[str] = None


class ChunkStatus(str, Enum):
    """Status of individual audio chunks for progressive processing."""
    pending = "pending"
    downloading = "downloading"  # Audio downloaded, waiting to be split
    split = "split"              # Audio split into chunk WAV, awaiting separation
    separating = "separating"    # Being processed by AI
    encoding = "encoding"        # Being encoded to MP3
    completed = "completed"      # Ready for playback
    failed = "failed"


class ChunkInfo(BaseModel):
    """Information about a single audio chunk."""
    index: int = Field(..., description="Chunk index (0-based)")
    status: ChunkStatus = Field(default=ChunkStatus.pending)
    progress: float = Field(default=0.0, description="Progress 0.0-1.0 for this chunk")
    start_time: float = Field(..., description="Start time in seconds")
    end_time: float = Field(..., description="End time in seconds")
    duration: float = Field(..., description="Chunk duration in seconds")
    file_ready: bool = Field(default=False, description="Whether the chunk file is ready for download")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class JobCreateRequest(BaseModel):
    url: HttpUrl = Field(..., description="Audio or video URL to download via yt-dlp")
    stems: Literal[2] = Field(default=2, description="Number of stems to create (vocals + accompaniment)")
    skip_cache: bool = Field(default=False, description="Skip cache lookup (useful for development/testing)")


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    stems: int
    message: Optional[str]
    progress: Optional[float]
    error_detail: Optional[str]
    failure_stage: Optional[str] = None
    failure_code: Optional[str] = None
    failure_recoverable: Optional[bool] = None
    created_at: datetime
    updated_at: datetime
    # Chunking support
    chunking_enabled: bool = Field(default=False, description="Whether this job uses chunked processing")
    total_duration: Optional[float] = Field(default=None, description="Total audio duration in seconds")
    chunk_duration: float = Field(default=60.0, description="Target chunk duration in seconds")
    total_chunks: int = Field(default=0, description="Total number of chunks")
    chunks_completed: int = Field(default=0, description="Number of chunks completed")
    chunks: List[ChunkInfo] = Field(default_factory=list, description="Individual chunk status")
    processing_stats: Dict[str, Any] = Field(default_factory=dict, description="Local processing diagnostics")
    update: Optional[UpdateInfo] = Field(default=None, description="Available app update info")

    @classmethod
    def _get_update_info(cls) -> Optional[UpdateInfo]:
        ver = os.environ.get("HARAMMUTE_UPDATE_VERSION")
        if not ver:
            return None
        return UpdateInfo(
            version=ver,
            severity=os.environ.get("HARAMMUTE_UPDATE_SEVERITY", "minor"),
            message=os.environ.get("HARAMMUTE_UPDATE_MESSAGE", ""),
            download_url=os.environ.get("HARAMMUTE_UPDATE_DOWNLOAD_URL") or None,
        )

    @classmethod
    def from_job(cls, job: Job) -> "JobStatusResponse":
        # Build chunk info from job's chunk data
        chunks = []
        chunks_completed = 0
        chunk_ready_by_index = {}
        if hasattr(job, 'chunks') and job.chunks:
            for chunk_data in job.chunks:
                chunk_info = ChunkInfo(
                    index=chunk_data.get('index', 0),
                    status=ChunkStatus(chunk_data.get('status', 'pending')),
                    progress=chunk_data.get('progress', 0.0),
                    start_time=chunk_data.get('start_time', 0.0),
                    end_time=chunk_data.get('end_time', 0.0),
                    duration=chunk_data.get('duration', 0.0),
                    file_ready=chunk_data.get('file_ready', False),
                    error=chunk_data.get('error'),
                )
                chunks.append(chunk_info)
                chunk_ready_by_index[chunk_info.index] = chunk_info.file_ready

        # Match the remote pipeline contract: only count contiguous ready chunks
        # from index 0 so clients never skip over an earlier missing chunk.
        if chunk_ready_by_index:
            next_index = 0
            while chunk_ready_by_index.get(next_index, False):
                chunks_completed += 1
                next_index += 1

        error_detail = job.error_detail or ""
        failure_code = getattr(job, "failure_code", None)
        if failure_code is None and "local worker could not start" in error_detail.lower():
            failure_code = "desktop_runtime_failed"

        return cls(
            job_id=job.job_id,
            status=job.status,
            stems=job.stems,
            message=job.message,
            progress=job.progress,
            error_detail=job.error_detail,
            failure_stage=getattr(job, "failure_stage", None),
            failure_code=failure_code,
            failure_recoverable=getattr(job, "failure_recoverable", None),
            created_at=job.created_at,
            updated_at=job.updated_at,
            chunking_enabled=getattr(job, 'chunking_enabled', False),
            total_duration=getattr(job, 'total_duration', None),
            chunk_duration=getattr(job, 'chunk_duration', 60.0),
            total_chunks=len(chunks),
            chunks_completed=chunks_completed,
            chunks=chunks,
            processing_stats=getattr(job, 'processing_stats', {}) or {},
            update=cls._get_update_info(),
        )


class JobResultResponse(JobStatusResponse):
    download_url: Optional[str]
    preview_url: Optional[str]
    available_stems: List[str] = Field(default_factory=list)

    @classmethod
    def from_job(
        cls,
        job: Job,
        download_url: Optional[str],
        preview_url: Optional[str],
        stems: List[str],
    ) -> "JobResultResponse":
        base = JobStatusResponse.from_job(job)
        data = base.model_dump()
        data.update(
            {
                "download_url": download_url,
                "preview_url": preview_url,
                "available_stems": stems,
            }
        )
        return cls(**data)
