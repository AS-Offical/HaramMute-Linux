"""Job processing pipeline for HaramMute (Linux build).

Pure-Python replacement for the compiled Windows ``pipeline`` module.
Orchestrates: download -> WAV conversion -> duration probe ->
single-file or chunked separation -> MP3 packaging -> completion.

Status transitions: queued -> downloading -> separating -> packaging
-> completed | failed. Chunked jobs update per-chunk entries
progressively so clients can start playback early.
"""

from __future__ import annotations

import logging
import math
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .jobs import Job, JobStore, JobStatus
from . import local_processing as lp
from .limits import MAX_VIDEO_SECONDS

logger = logging.getLogger("app.pipeline")

# Jobs at or below this duration are processed as a single file;
# longer audio is split into ~60s chunks for progressive playback.
CHUNK_THRESHOLD_SECONDS = float(
    __import__("os").environ.get("MUSIC_REMOVER_CHUNK_THRESHOLD", "120")
)

PROGRESS_DOWNLOAD_START = 0.02
PROGRESS_DOWNLOAD_END = 0.15
PROGRESS_SEPARATE_START = 0.15
PROGRESS_SEPARATE_END = 0.90
PROGRESS_PACKAGE = 0.95


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_update(store: JobStore, job_id: str, **fields) -> None:
    try:
        store.update_job(job_id, **fields)
    except Exception:  # noqa: BLE001 - never crash the worker on a status write
        logger.debug("Status update failed for job %s: %s", job_id, traceback.format_exc())


def process_job(job_id: str, job_store: JobStore) -> None:
    """Process one job end-to-end. Runs inside the bounded thread pool."""
    job = job_store.get_job(job_id)
    if job is None:
        logger.error("Job %s not found; skipping", job_id)
        return

    started = _now()
    stats: dict = {"started_at": started.isoformat()}
    work_dir = settings.data_dir / "jobs" / job_id / "work"
    result_dir = settings.data_dir / "jobs" / job_id / "result"
    result_dir.mkdir(parents=True, exist_ok=True)

    try:
        # ------------------------------------------------------------------
        # Stage 1: download + convert + probe
        # ------------------------------------------------------------------
        _safe_update(
            job_store, job_id,
            status=JobStatus.downloading,
            message="Downloading audio",
            progress=PROGRESS_DOWNLOAD_START,
        )
        _mark_failure_stage(stats, "download")

        def download_progress(fraction: float) -> None:
            span = PROGRESS_DOWNLOAD_END - PROGRESS_DOWNLOAD_START
            _safe_update(
                job_store, job_id,
                progress=round(PROGRESS_DOWNLOAD_START + span * fraction, 4),
            )

        source_file = lp.download_audio(
            job.source_url,
            work_dir,
            progress_callback=download_progress,
            delay_between_attempts=settings.download_delay,
        )
        stats["download_seconds"] = round((_now() - started).total_seconds(), 2)

        _mark_failure_stage(stats, "conversion")
        wav_path = lp.convert_to_wav(source_file, work_dir)
        _mark_failure_stage(stats, "validation")
        duration = lp.probe_duration(wav_path)
        if duration > MAX_VIDEO_SECONDS:
            raise ValueError(
                f"Media is longer than the 90-minute processing limit ({duration / 60:.1f} minutes)"
            )
        stats["duration_seconds"] = round(duration, 2)
        logger.info("Audio duration: %.2f seconds", duration)

        use_chunks = duration > CHUNK_THRESHOLD_SECONDS
        chunk_duration = float(getattr(job, "chunk_duration", 60.0) or 60.0)
        if use_chunks:
            total_chunks = max(1, math.ceil(duration / chunk_duration))
            chunks = [
                {
                    "index": index,
                    "status": "pending",
                    "progress": 0.0,
                    "start_time": round(index * chunk_duration, 3),
                    "end_time": round(min((index + 1) * chunk_duration, duration), 3),
                    "duration": round(min(chunk_duration, duration - index * chunk_duration), 3),
                    "file_ready": False,
                    "error": None,
                }
                for index in range(total_chunks)
            ]
            _safe_update(
                job_store, job_id,
                chunking_enabled=True,
                total_duration=round(duration, 2),
                total_chunks=total_chunks,
                chunks=chunks,
            )
        else:
            logger.info("Job %s using single-file processing (duration: %.1fs)", job_id, duration)
            _safe_update(job_store, job_id, total_duration=round(duration, 2))

        # ------------------------------------------------------------------
        # Stage 2: separation
        # ------------------------------------------------------------------
        separation_started = _now()
        _safe_update(
            job_store, job_id,
            status=JobStatus.separating,
            message="Separating vocals from music",
        )

        stems_files: dict[str, Path] = {}
        chunk_files: dict[int, Path] = {}
        chunk_vocal_wavs: dict[int, Path] = {}

        if not use_chunks:
            _separate_single_file(
                job_store, job_id, wav_path, result_dir, stats, stems_files
            )
        else:
            _separate_chunked(
                job_store, job_id, wav_path, work_dir, result_dir,
                chunks, chunk_duration, chunk_files, chunk_vocal_wavs, stats,
            )
            _mark_failure_stage(stats, "packaging")
            full_vocals = lp.concatenate_wav_chunks_to_mp3(
                [chunk_vocal_wavs[index] for index in sorted(chunk_vocal_wavs)],
                result_dir / "vocals.mp3",
                quality=settings.encoding_quality,
            )
            stems_files["vocals"] = full_vocals
            for vocal_wav in chunk_vocal_wavs.values():
                try:
                    vocal_wav.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Could not remove temporary vocal chunk %s: %s", vocal_wav, exc)
            stats["assembled_vocals"] = True

        stats["separation_seconds"] = round(
            (_now() - separation_started).total_seconds(), 2
        )

        # ------------------------------------------------------------------
        # Stage 3: finalize
        # ------------------------------------------------------------------
        _safe_update(
            job_store, job_id,
            status=JobStatus.packaging,
            message="Finalizing",
            progress=PROGRESS_PACKAGE,
            stems_files={k: str(v) for k, v in stems_files.items()},
            chunk_files={str(k): str(v) for k, v in chunk_files.items()},
        )

        completed_at = _now()
        stats.pop("_failure_stage", None)
        stats["total_seconds"] = round((completed_at - started).total_seconds(), 2)
        stats["mode"] = "chunked" if use_chunks else "single"
        logger.info("Job %s completed in %.1fs", job_id, stats["total_seconds"])

        _safe_update(
            job_store, job_id,
            status=JobStatus.completed,
            message="Completed",
            progress=1.0,
            processing_stats=stats,
        )

    except Exception as exc:  # noqa: BLE001 - report every failure into the job
        stage = stats.pop("_failure_stage", "processing")
        logger.exception("Job %s failed during %s: %s", job_id, stage, exc)
        failed_at = _now()
        stats["failed_after_seconds"] = round((failed_at - started).total_seconds(), 2)
        _safe_update(
            job_store, job_id,
            status=JobStatus.failed,
            message=f"Processing failed during {stage}",
            error_detail=f"{type(exc).__name__}: {exc}",
            failure_stage=stage,
            failure_code=f"{stage}_failed",
            failure_recoverable=True,
            processing_stats=stats,
        )


def _mark_failure_stage(stats: dict, stage: str) -> None:
    stats["_failure_stage"] = stage


def _encode_chunk_vocals(
    vocals_wav: Path,
    result_dir: Path,
    name: str,
    *,
    remove_source: bool = True,
) -> Path:
    target = result_dir / name
    lp.transcode_to_mp3(vocals_wav, target, quality=settings.encoding_quality)
    if remove_source:
        try:
            vocals_wav.unlink(missing_ok=True)
        except OSError:
            pass
    return target


def _separate_single_file(
    job_store: JobStore,
    job_id: str,
    wav_path: Path,
    result_dir: Path,
    stats: dict,
    stems_files: dict,
) -> None:
    _mark_failure_stage(stats, "separation")
    _safe_update(job_store, job_id, progress=0.25, message="Running AI vocal separation")

    outcome = lp.separate_vocals(
        wav_path,
        output_dir=result_dir,
        model_cache_dir=settings.data_dir / "models" / "audio-separator",
        force_cpu=settings.force_cpu,
    )
    stats["separation_runtime_seconds"] = outcome["seconds"]
    stats["execution_device"] = outcome.get("device", "unknown")
    stats["execution_providers"] = outcome.get("providers", [])
    _safe_update(job_store, job_id, progress=0.85, message="Encoding vocals")

    _mark_failure_stage(stats, "packaging")
    vocals_mp3 = _encode_chunk_vocals(outcome["vocals"], result_dir, "vocals.mp3")
    stems_files["vocals"] = vocals_mp3


def _separate_chunked(
    job_store: JobStore,
    job_id: str,
    wav_path: Path,
    work_dir: Path,
    result_dir: Path,
    chunks: list[dict],
    chunk_duration: float,
    chunk_files: dict,
    chunk_vocal_wavs: dict[int, Path],
    stats: dict,
) -> None:
    total = len(chunks)
    model_cache = settings.data_dir / "models" / "audio-separator"

    for chunk in chunks:
        index = int(chunk["index"])
        start = float(chunk["start_time"])
        end = float(chunk["end_time"])
        base = PROGRESS_SEPARATE_START + (index / total) * (
            PROGRESS_SEPARATE_END - PROGRESS_SEPARATE_START
        )

        try:
            job_store.update_chunk(
                job_id, index, status="split", progress=0.0
            )
            _safe_update(
                job_store, job_id,
                progress=round(base, 4),
                message=f"Processing chunk {index + 1}/{total}",
            )
            _mark_failure_stage(stats, f"chunk_{index}_split")
            chunk_wav = lp.split_audio_chunk(
                wav_path, start, end, work_dir / f"chunk_{index}.wav"
            )

            job_store.update_chunk(job_id, index, status="separating")
            _mark_failure_stage(stats, f"chunk_{index}_separation")
            outcome = lp.separate_vocals(
                chunk_wav,
                output_dir=result_dir,
                model_cache_dir=model_cache,
                force_cpu=settings.force_cpu,
            )
            stats.setdefault("chunk_execution_providers", {})[str(index)] = {
                "device": outcome.get("device", "unknown"),
                "providers": outcome.get("providers", []),
            }

            job_store.update_chunk(job_id, index, status="encoding", progress=0.9)
            _mark_failure_stage(stats, f"chunk_{index}_encoding")
            vocals_mp3 = _encode_chunk_vocals(
                outcome["vocals"], result_dir, f"vocals_chunk_{index}.mp3",
                remove_source=False,
            )

            chunk_files[index] = vocals_mp3
            chunk_vocal_wavs[index] = outcome["vocals"]
            job_store.update_chunk(
                job_id, index,
                status="completed",
                progress=1.0,
                file_ready=True,
                error=None,
            )
            current_job = job_store.get_job(job_id)
            done = (
                sum(
                    1 for item in current_job.chunks
                    if item.get("status") == "completed" and item.get("file_ready")
                )
                if current_job is not None
                else index + 1
            )
            span = PROGRESS_SEPARATE_END - PROGRESS_SEPARATE_START
            _safe_update(
                job_store, job_id,
                progress=round(PROGRESS_SEPARATE_START + span * ((done) / total), 4),
            )

        except Exception as exc:  # noqa: BLE001 - isolate per-chunk failures
            logger.exception("Chunk %d of job %s failed: %s", index, job_id, exc)
            job_store.update_chunk(
                job_id, index,
                status="failed",
                file_ready=False,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

    _mark_failure_stage(stats, "packaging")
