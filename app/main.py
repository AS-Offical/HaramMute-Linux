import asyncio
import fcntl
import ipaddress
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, EmailStr

from .config import settings

# Cloud-only imports - use importlib so PyInstaller's static analysis doesn't find them.
_pkg = __package__ or (__name__.rsplit(".", 1)[0] if "." in __name__ else "app")

if not settings.local_mode:
    import importlib
    import httpx  # Only needed for Polar.sh API calls

    # Sentry is optional - only used in cloud deployments
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        SENTRY_AVAILABLE = True
    except ImportError:
        SENTRY_AVAILABLE = False

    # Initialize Sentry for error tracking (only if available and DSN is configured)
    if SENTRY_AVAILABLE and (sentry_dsn := os.environ.get("SENTRY_DSN")):
        is_dev = os.environ.get("SENTRY_ENVIRONMENT") == "development"
        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
            traces_sample_rate=1.0 if is_dev else 0.1,
            profiles_sample_rate=0.5 if is_dev else 0.1,
            integrations=[
                StarletteIntegration(failed_request_status_codes=set(range(500, 599))),
                FastApiIntegration(failed_request_status_codes=set(range(500, 599))),
            ],
        )

    _auth = importlib.import_module(".auth", package=_pkg)
    get_api_key_record = _auth.get_api_key_record
    get_or_create_api_key = _auth.get_or_create_api_key
    normalize_email = _auth.normalize_email
    revoke_api_key = _auth.revoke_api_key
    rotate_api_key = _auth.rotate_api_key

    _rate_limit = importlib.import_module(".rate_limit", package=_pkg)
    check_and_record_rate_limit = _rate_limit.check_and_record_rate_limit

    _tiers = importlib.import_module(".tiers", package=_pkg)
    get_daily_limit_seconds = _tiers.get_daily_limit_seconds

    _usage = importlib.import_module(".usage", package=_pkg)
    check_usage_limit = _usage.check_usage_limit
else:
    # Local/desktop mode - no cloud dependencies
    SENTRY_AVAILABLE = False

    def _cloud_only_stub(name):
        def stub(*args, **kwargs):
            raise RuntimeError(
                f"Cloud function '{name}' called in local mode! "
                "This indicates a misconfiguration. Check MUSIC_REMOVER_LOCAL_MODE."
            )
        return stub

    get_api_key_record = _cloud_only_stub("get_api_key_record")
    get_or_create_api_key = _cloud_only_stub("get_or_create_api_key")
    revoke_api_key = _cloud_only_stub("revoke_api_key")
    rotate_api_key = _cloud_only_stub("rotate_api_key")
    check_and_record_rate_limit = _cloud_only_stub("check_and_record_rate_limit")
    get_daily_limit_seconds = _cloud_only_stub("get_daily_limit_seconds")
    check_usage_limit = _cloud_only_stub("check_usage_limit")

    def normalize_email(email):
        return email.lower().strip()

    class _HttpxStub:
        TimeoutException = Exception

    httpx = _HttpxStub()

    # Stub sentry_sdk so references in code don't crash
    class _SentryStub:
        @staticmethod
        def set_user(*args, **kwargs):
            pass
        @staticmethod
        def capture_message(*args, **kwargs):
            pass

    sentry_sdk = _SentryStub()

from .jobs import Job, JobCapacityExceeded, JobStatus, JobStore
from .limits import (
    JOBS_RATE_LIMIT_PER_HOUR,
    MAX_CONCURRENT_JOBS,
    MAX_QUEUED_JOBS,
)
from .schemas import JobCreateRequest, JobResultResponse, JobStatusResponse


async def run_sync(func, *args, **kwargs):
    """Run a blocking function in a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _require_cloud_mode() -> None:
    """Raise if a cloud-only endpoint is called in local mode."""
    if settings.local_mode:
        raise HTTPException(
            status_code=503,
            detail="This endpoint is not available in local/desktop mode. Use cloud version.",
        )


# Polar subscription check models
class SubscriptionCheckRequest(BaseModel):
    email: EmailStr


class SubscriptionCheckResponse(BaseModel):
    subscribed: bool
    customer_id: str | None = None
    plan: str | None = None
    is_trial: bool = False
    trial_ends_at: str | None = None
    reason: str | None = None


# Polar checkout models
class CreateCheckoutRequest(BaseModel):
    email: EmailStr | None = None  # Optional - user can enter on checkout page
    billing_cycle: Literal["monthly", "yearly"] = "monthly"


class CreateCheckoutResponse(BaseModel):
    checkout_url: str
    checkout_id: str | None = None


class CustomerPortalRequest(BaseModel):
    email: EmailStr


class CustomerPortalResponse(BaseModel):
    portal_url: str


class ApiKeyGenerateRequest(BaseModel):
    email: EmailStr


class ApiKeyGenerateResponse(BaseModel):
    api_key: str
    email: EmailStr
    customer_id: str | None = None
    plan: str | None = None
    is_trial: bool = False
    trial_ends_at: str | None = None


logger = logging.getLogger("harammute")


def _capture_local_desktop_event(
    event_name: str,
    properties: dict,
    *,
    event_key: str,
) -> None:
    if not settings.local_mode:
        return
    try:
        from .desktop_telemetry import capture_desktop_event

        capture_desktop_event(event_name, properties, event_key=event_key)
    except Exception as exc:
        logger.debug("Desktop telemetry failed for %s: %s", event_name, exc)


def _capture_local_worker_failure(job: Job, error: Exception, stage: str) -> None:
    try:
        from .desktop_telemetry import error_fingerprint, sanitize_error_summary

        summary = sanitize_error_summary(error)
        elapsed = max(
            0.0,
            (datetime.now(timezone.utc) - job.created_at).total_seconds(),
        )
        _capture_local_desktop_event(
            "desktop_job_failed",
            {
                "job_id": job.job_id,
                "stems": job.stems,
                "elapsed_seconds": round(elapsed, 3),
                "failure_stage": stage,
                "failure_code": "desktop_runtime_failed",
                "failure_recoverable": False,
                "error_summary": summary,
                "error_fingerprint": error_fingerprint(summary),
                "chunking_enabled": bool(getattr(job, "chunking_enabled", False)),
                "total_chunks": len(getattr(job, "chunks", []) or []),
            },
            event_key=f"job-failed:{job.job_id}",
        )
    except Exception as exc:
        logger.debug("Desktop worker failure telemetry failed: %s", exc)
logging.basicConfig(level=logging.INFO)

SUBSCRIPTION_CACHE_TTL_SECONDS = 60 * 60 * 24


async def _get_current_user(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    if settings.local_mode or settings.dev_mode:
        if settings.dev_mode and not settings.local_mode:
            logger.warning("dev_mode is enabled outside local_mode; authentication bypassed")
        return {"email": "dev@local", "bypass": True}
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    record = await run_sync(get_api_key_record, x_api_key)
    if not record or not record.get("active", True):
        raise HTTPException(status_code=401, detail="Invalid API key")
    email = record.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid API key")
    await _ensure_subscription_active(email)
    # Set user context for Sentry error tracking
    sentry_sdk.set_user({"email": email, "id": x_api_key[:12] + "..."})
    return {"email": email, "tier": record.get("tier"), "bypass": False, "api_key": x_api_key}


def _enforce_job_owner(job: Job, user: dict) -> None:
    if user.get("bypass"):
        return
    job_email = (job.owner_email or "").lower()
    user_email = (user.get("email") or "").lower()
    if job_email != user_email:
        raise HTTPException(status_code=403, detail="Forbidden")


def _enforce_usage_limit(user: dict) -> None:
    if settings.dev_mode:
        return
    if user.get("bypass"):
        return
    email = user.get("email")
    tier = user.get("tier")
    limit = get_daily_limit_seconds(tier)
    if not email or not check_usage_limit(email, limit_seconds=limit):
        raise HTTPException(
            status_code=429,
            detail=f"Daily usage limit exceeded ({limit} seconds)",
        )


def _enforce_jobs_rate_limit(email: str) -> None:
    if settings.local_mode or settings.dev_mode:
        return
    if not check_and_record_rate_limit(f"jobs:email:{email}", JOBS_RATE_LIMIT_PER_HOUR, window="hour"):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded (max {JOBS_RATE_LIMIT_PER_HOUR}/hour)",
        )


def _enforce_concurrency_limits(email: str) -> None:
    if settings.dev_mode:
        return
    queued = job_store.count_jobs_by_owner(email, {JobStatus.queued})
    if queued >= MAX_QUEUED_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Queue full (max {MAX_QUEUED_JOBS} pending)",
        )

    # The desktop executor is the active-job scheduler in local mode. New
    # jobs may remain queued while its fixed worker count is busy.
    if settings.local_mode:
        return

    active_statuses = {JobStatus.downloading, JobStatus.separating, JobStatus.packaging}
    active = job_store.count_jobs_by_owner(email, active_statuses)
    if active >= MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many concurrent jobs (max {MAX_CONCURRENT_JOBS})",
        )


def _reload_jobs_volume() -> None:
    """Reload the jobs volume to see files written by other containers."""
    if settings.local_mode:
        return  # No volume in local mode
    try:
        import modal
        vol = modal.Volume.from_name("music-remover-chunked-jobs", create_if_missing=False)
        vol.reload()
    except Exception as e:
        logger.debug("Volume reload skipped: %s", e)

app = FastAPI(title="HaramMute Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[] if settings.local_mode else ["*"],
    allow_origin_regex=(
        r"^(chrome-extension|moz-extension)://[a-zA-Z0-9._@{}-]+$"
        if settings.local_mode else None
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_local_client_boundary(request: Request, call_next):
    """Keep the unauthenticated desktop API inaccessible from the LAN."""
    if settings.local_mode:
        host = request.client.host if request.client else ""
        try:
            address = ipaddress.ip_address(host)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if not address.is_loopback:
                return HTMLResponse("Local HaramMute API only", status_code=403)
        except ValueError:
            return HTMLResponse("Local HaramMute API only", status_code=403)
    return await call_next(request)

job_store = JobStore()
_server_instance_lock = None

# Bounded thread pool for local mode (dev only) - prevents resource exhaustion
_local_executor: Optional[ThreadPoolExecutor] = None
_local_executor_lock = threading.Lock()


def _get_local_executor() -> ThreadPoolExecutor:
    """Lazily create a bounded thread pool for local mode."""
    global _local_executor
    with _local_executor_lock:
        if _local_executor is None:
            worker_count = max(1, min(settings.max_workers, MAX_CONCURRENT_JOBS))
            _local_executor = ThreadPoolExecutor(max_workers=worker_count)
        return _local_executor


def _spawn_job_worker(job_id: str, source_url: str, stems: int) -> Optional[str]:
    """
    Spawn the job worker function on Modal.
    Returns the function call ID if successful, None if running locally.
    """
    if settings.local_mode:
        # Local mode: run in bounded thread pool (for development)
        from .pipeline import process_job

        def run_local():
            try:
                process_job(job_id, job_store)
            except Exception as e:
                logger.exception("Local job %s failed: %s", job_id, e)
                failed_job = job_store.update_job(
                    job_id,
                    status=JobStatus.failed,
                    message="Desktop processing runtime stopped unexpectedly",
                    error_detail=f"Local worker stopped unexpectedly: {type(e).__name__}: {e}",
                    failure_stage="processing_runtime",
                    failure_code="desktop_runtime_failed",
                    failure_recoverable=False,
                )
                if failed_job is not None:
                    _capture_local_worker_failure(failed_job, e, "processing_runtime")

        _get_local_executor().submit(run_local)
        return None

    # Modal mode: spawn the worker function
    try:
        import modal
        worker_fn = modal.Function.from_name("music-remover-chunked", "process_job_worker")
        call = worker_fn.spawn(job_id, source_url, stems)
        logger.info("Spawned job %s with Modal call ID: %s", job_id, call.object_id)
        return call.object_id
    except Exception as e:
        logger.error("Failed to spawn job %s: %s", job_id, e)
        # Update job status to failed - but don't raise, return the job in failed state
        job_store.update_job(
            job_id,
            status=JobStatus.failed,
            message="Failed to start job",
            error_detail=str(e),
        )
        return None  # Return None instead of raising - job exists in failed state


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Shutdown the local thread pool to avoid hanging on dev shutdowns."""
    global _local_executor
    with _local_executor_lock:
        if _local_executor is not None:
            _local_executor.shutdown(wait=False)
            _local_executor = None
            logger.info("Local executor shut down")
    global _server_instance_lock
    if _server_instance_lock is not None:
        fcntl.flock(_server_instance_lock.fileno(), fcntl.LOCK_UN)
        _server_instance_lock.close()
        _server_instance_lock = None


@app.on_event("startup")
async def recover_local_runtime() -> None:
    """Recover persistent queued jobs after a desktop restart."""
    if not settings.local_mode:
        return
    global _server_instance_lock
    _server_instance_lock = (settings.data_dir / ".server.lock").open("a+")
    try:
        fcntl.flock(_server_instance_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        _server_instance_lock.close()
        _server_instance_lock = None
        raise RuntimeError(
            f"Another HaramMute server is already using data directory {settings.data_dir}"
        ) from exc
    queued_jobs = await run_sync(job_store.recover_interrupted_local_jobs)
    if queued_jobs:
        logger.info("Resuming %d queued local jobs from the previous session", len(queued_jobs))
    for job in queued_jobs:
        await run_sync(_spawn_job_worker, job.job_id, job.source_url, job.stems)


@app.get("/health")
async def healthcheck() -> dict:
    resp = {
        "status": "ok",
        "service": "harammute",
        "version": os.environ.get("HARAMMUTE_VERSION", "unknown"),
    }
    update_ver = os.environ.get("HARAMMUTE_UPDATE_VERSION")
    if update_ver:
        resp["update"] = {
            "version": update_ver,
            "severity": os.environ.get("HARAMMUTE_UPDATE_SEVERITY", "minor"),
            "message": os.environ.get("HARAMMUTE_UPDATE_MESSAGE", ""),
            "download_url": os.environ.get("HARAMMUTE_UPDATE_DOWNLOAD_URL") or None,
        }
    return resp


@app.get("/dev-check")
async def dev_check() -> dict[str, str]:
    """Returns 200 only in dev environment, 404 in prod. Use to verify which env you're hitting."""
    env = os.environ.get("SENTRY_ENVIRONMENT", "production")
    if env != "development":
        raise HTTPException(status_code=404, detail="Not Found")
    return {"environment": "development", "status": "You are hitting the DEV environment"}


@app.get("/ping")
async def ping() -> dict[str, str]:
    """Health check endpoint required by RunPod Load Balancing."""
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    """Landing page shown when user opens the server URL directly."""
    version = os.environ.get("HARAMMUTE_VERSION", "unknown")
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HaramMute - Server Running</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #F8F5F0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #1A1A2E;
        }
        .container {
            text-align: center;
            padding: 2rem;
            max-width: 480px;
        }
        .logo {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            margin-bottom: 2rem;
        }
        .logo-icon {
            width: 48px;
            height: 48px;
        }
        .logo-text {
            font-size: 1.75rem;
            font-weight: 700;
            color: #1A1A2E;
        }
        .logo-text span {
            color: #E8736A;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #E6F4EA;
            border: 1px solid #34A853;
            padding: 8px 16px;
            border-radius: 24px;
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
            font-weight: 500;
            color: #34A853;
        }
        .status-dot {
            width: 8px;
            height: 8px;
            background: #34A853;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        h1 {
            font-size: 2rem;
            margin-bottom: 0.75rem;
            font-weight: 700;
            color: #1A1A2E;
        }
        h1 span {
            color: #E8736A;
        }
        .description {
            color: #6E6E80;
            line-height: 1.6;
            margin-bottom: 2rem;
            font-size: 1rem;
        }
        .card {
            background: #FFFFFF;
            border: 1px solid #E8E4DE;
            border-radius: 16px;
            padding: 1.5rem;
            text-align: left;
            box-shadow: 0 2px 16px rgba(26, 26, 46, 0.06);
        }
        .card h2 {
            font-size: 1rem;
            margin-bottom: 1rem;
            color: #1A1A2E;
            font-weight: 600;
        }
        .step {
            display: flex;
            gap: 1rem;
            margin-bottom: 1rem;
            align-items: flex-start;
        }
        .step:last-child { margin-bottom: 0; }
        .step-num {
            width: 28px;
            height: 28px;
            background: #FDEAEA;
            color: #E8736A;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.8rem;
            font-weight: 600;
            flex-shrink: 0;
        }
        .step-text {
            color: #6E6E80;
            font-size: 0.9rem;
            line-height: 1.5;
            padding-top: 4px;
        }
        .footer {
            margin-top: 2rem;
            font-size: 0.8rem;
            color: #9E9EAE;
        }
        .footer code {
            background: #E8E4DE;
            padding: 2px 8px;
            border-radius: 4px;
            font-family: 'SF Mono', Consolas, monospace;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <img class="logo-icon" src="data:image/png;base64,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" alt="HaramMute">
            <span class="logo-text">Haram<span>Mute</span></span>
        </div>
        <div class="status-badge">
            <span class="status-dot"></span>
            Server Running
        </div>
        <h1>Watch Videos <span>Without Music</span></h1>
        <p class="description">
            The vocal separation server is running and ready to process audio. You can close this tab.
        </p>
        <div class="card">
            <h2>How to use</h2>
            <div class="step">
                <span class="step-num">1</span>
                <span class="step-text">Install the HaramMute browser extension if you haven'tx</span>
            </div>
            <div class="step">
                <span class="step-num">2</span>
                <span class="step-text">Navigate to any YouTube video</span>
            </div>
            <div class="step">
                <span class="step-num">3</span>
                <span class="step-text">Click the extension icon to remove background music</span>
            </div>
        </div>
        <p class="footer">
            Server: <code>http://127.0.0.1:8765</code> · Version <code>__VERSION__</code>
        </p>
    </div>
</body>
</html>"""
    html = html.replace("__VERSION__", version)
    return HTMLResponse(content=html)


def _polar_configured() -> bool:
    # At least one product ID must be configured
    has_product = bool(settings.polar_product_id_monthly or settings.polar_product_id_yearly)
    return bool(settings.polar_api_key and settings.polar_org_id and has_product)


def _get_subscription_cache_store():
    try:
        import modal
        return modal.Dict.from_name("music-remover-chunked-subscription-cache", create_if_missing=True)
    except Exception as exc:
        logger.warning("Subscription cache unavailable: %s", exc)
        return None


def _subscription_cache_key(email: str) -> str:
    return f"sub:{normalize_email(email)}"


def _read_cached_subscription(email: str) -> Optional[SubscriptionCheckResponse]:
    store = _get_subscription_cache_store()
    if store is None:
        return None
    key = _subscription_cache_key(email)
    try:
        record = store.get(key)
    except Exception as exc:
        logger.warning("Failed to read subscription cache: %s", exc)
        return None
    if not record or not isinstance(record, dict):
        return None
    checked_at = record.get("checked_at")
    if not checked_at:
        return None
    try:
        checked_time = datetime.fromisoformat(checked_at)
    except Exception:
        return None
    age = (datetime.now(timezone.utc) - checked_time).total_seconds()
    if age > SUBSCRIPTION_CACHE_TTL_SECONDS:
        return None
    return SubscriptionCheckResponse(
        subscribed=record.get("subscribed", False),
        customer_id=record.get("customer_id"),
        plan=record.get("plan"),
        is_trial=record.get("is_trial", False),
        trial_ends_at=record.get("trial_ends_at"),
        reason=record.get("reason"),
    )


def _write_subscription_cache(email: str, subscription: SubscriptionCheckResponse) -> None:
    store = _get_subscription_cache_store()
    if store is None:
        return
    key = _subscription_cache_key(email)
    record = {
        "subscribed": subscription.subscribed,
        "customer_id": subscription.customer_id,
        "plan": subscription.plan,
        "is_trial": subscription.is_trial,
        "trial_ends_at": subscription.trial_ends_at,
        "reason": subscription.reason,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store[key] = record
    except Exception as exc:
        logger.warning("Failed to write subscription cache: %s", exc)


def _capture_subscription_issue(email: str, reason: str, detail: str) -> None:
    """Capture subscription issues to Sentry for alerting."""
    sentry_sdk.capture_message(
        f"Subscription issue: {detail}",
        level="warning",
        tags={"subscription_reason": reason, "error_type": "subscription_issue"},
        extras={"email": email},
    )


async def _ensure_subscription_active(email: str) -> None:
    if not _polar_configured():
        raise HTTPException(
            status_code=503,
            detail="Polar configuration is missing. Subscription checks disabled.",
        )
    cached = await run_sync(_read_cached_subscription, email)
    if cached:
        if cached.subscribed:
            return
        # Capture to Sentry and return specific error messages based on reason
        reason = cached.reason or "no_subscription"
        if cached.reason == "revoked":
            _capture_subscription_issue(email, reason, "Subscription expired")
            raise HTTPException(status_code=403, detail="Subscription expired")
        elif cached.reason == "canceled":
            _capture_subscription_issue(email, reason, "Subscription canceled")
            raise HTTPException(status_code=403, detail="Subscription canceled")
        elif cached.reason == "past_due":
            _capture_subscription_issue(email, reason, "Payment past due")
            raise HTTPException(status_code=403, detail="Payment past due")
        else:
            _capture_subscription_issue(email, reason, "No active subscription found")
            raise HTTPException(status_code=403, detail="No active subscription found")
    subscription = await _fetch_subscription_from_polar(email)
    await run_sync(_write_subscription_cache, email, subscription)
    if not subscription.subscribed:
        # Capture to Sentry and return specific error messages based on reason
        reason = subscription.reason or "no_subscription"
        if subscription.reason == "revoked":
            _capture_subscription_issue(email, reason, "Subscription expired")
            raise HTTPException(status_code=403, detail="Subscription expired")
        elif subscription.reason == "canceled":
            _capture_subscription_issue(email, reason, "Subscription canceled")
            raise HTTPException(status_code=403, detail="Subscription canceled")
        elif subscription.reason == "past_due":
            _capture_subscription_issue(email, reason, "Payment past due")
            raise HTTPException(status_code=403, detail="Payment past due")
        else:
            _capture_subscription_issue(email, reason, "No active subscription found")
            raise HTTPException(status_code=403, detail="No active subscription found")


async def _fetch_subscription_from_polar(email: EmailStr) -> SubscriptionCheckResponse:
    email = normalize_email(email)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # Step 1: Find customer by email
        logger.info("Checking subscription for email: %s", email)
        customers_resp = await client.get(
            "https://api.polar.sh/v1/customers/",
            params={
                "email": email,
                "organization_id": settings.polar_org_id,
            },
            headers={"Authorization": f"Bearer {settings.polar_api_key}"},
            timeout=10.0,
        )

        if customers_resp.status_code != 200:
            logger.error("Polar customers API error: %s - %s", customers_resp.status_code, customers_resp.text)
            return SubscriptionCheckResponse(subscribed=False, reason="no_customer")

        customers_data = customers_resp.json()
        customers = customers_data.get("items", [])
        logger.info("Found %d customers for email %s", len(customers), email)

        if not customers:
            logger.info("No Polar customer found for email: %s", email)
            return SubscriptionCheckResponse(subscribed=False, reason="no_customer")

        customer = customers[0]
        customer_id = customer["id"]
        logger.info("Customer ID: %s", customer_id)

        # Step 2: Get customer subscriptions (don't filter by active - get all and check status)
        subs_resp = await client.get(
            "https://api.polar.sh/v1/subscriptions/",
            params={
                "customer_id": customer_id,
            },
            headers={"Authorization": f"Bearer {settings.polar_api_key}"},
            timeout=10.0,
        )

        if subs_resp.status_code != 200:
            logger.error("Polar subscriptions API error: %s - %s", subs_resp.status_code, subs_resp.text)
            return SubscriptionCheckResponse(subscribed=False, customer_id=customer_id, reason="api_error")

        subs_data = subs_resp.json()
        subscriptions = subs_data.get("items", [])
        logger.info("Found %d subscriptions for customer %s", len(subscriptions), customer_id)

        # Log all subscriptions for debugging
        for sub in subscriptions:
            sub_status = sub.get("status")
            sub_product_id = sub.get("product_id")
            sub_product_name = sub.get("product", {}).get("name", "Unknown")
            logger.info("  Subscription: status=%s, product_id=%s, product_name=%s",
                        sub_status, sub_product_id, sub_product_name)

        # Check for active or trialing subscription
        # Accept ANY active subscription from this org (don't filter by product_id)
        inactive_reason = None
        for sub in subscriptions:
            sub_status = sub.get("status")
            if sub_status in ("active", "trialing"):
                plan_name = sub.get("product", {}).get("name", "Pro")
                trial_ends = sub.get("trial_ends_at")
                is_trial = sub_status == "trialing"

                logger.info("Found active subscription: %s (is_trial=%s)", plan_name, is_trial)
                return SubscriptionCheckResponse(
                    subscribed=True,
                    customer_id=customer_id,
                    plan=plan_name,
                    is_trial=is_trial,
                    trial_ends_at=trial_ends,
                    reason=None,
                )
            elif sub_status in ("canceled", "revoked", "past_due"):
                # Track the reason for inactive subscription
                inactive_reason = sub_status

        logger.info("No active subscription for customer: %s (reason=%s)", customer_id, inactive_reason or "no_subscription")
        return SubscriptionCheckResponse(
            subscribed=False,
            customer_id=customer_id,
            reason=inactive_reason or "no_subscription"
        )


@app.post("/check-subscription", response_model=SubscriptionCheckResponse)
async def check_subscription(payload: SubscriptionCheckRequest) -> SubscriptionCheckResponse:
    """
    Check if a user has an active Polar.sh subscription by email.
    Returns subscription status for gating cloud processing features.
    """
    _require_cloud_mode()
    # If Polar is not configured, allow all (for local development)
    if not settings.polar_api_key or not settings.polar_org_id:
        logger.warning("Polar not configured - allowing all subscriptions")
        return SubscriptionCheckResponse(subscribed=True, plan="development")

    try:
        return await _fetch_subscription_from_polar(payload.email)

    except httpx.TimeoutException:
        logger.error("Polar API timeout")
        # On timeout, fail open for better UX (or fail closed for security)
        return SubscriptionCheckResponse(subscribed=False)
    except Exception as e:
        logger.exception("Polar subscription check failed: %s", e)
        return SubscriptionCheckResponse(subscribed=False)


@app.post("/create-checkout", response_model=CreateCheckoutResponse)
async def create_checkout(payload: CreateCheckoutRequest) -> CreateCheckoutResponse:
    """
    Create a Polar checkout session with a 3-day trial period.
    Returns a checkout URL that the user can be redirected to.
    """
    _require_cloud_mode()
    # Require Polar configuration
    if not settings.polar_api_key:
        logger.error("Polar not configured - cannot create checkout")
        raise HTTPException(
            status_code=500,
            detail="Payment system not configured. Please contact support.",
        )

    # Select product ID based on billing cycle
    if payload.billing_cycle == "yearly":
        product_id = settings.polar_product_id_yearly
    else:
        product_id = settings.polar_product_id_monthly

    if not product_id:
        logger.error("Product ID not configured for %s billing", payload.billing_cycle)
        raise HTTPException(
            status_code=500,
            detail=f"Payment system not configured for {payload.billing_cycle} plan.",
        )

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            # Create checkout session with trial period
            checkout_data = {
                "products": [product_id],
                "allow_trial": True,
                "trial_interval": "day",
                "trial_interval_count": 3,
                # Success URL - user will be redirected here after checkout
                # Using a simple confirmation page or back to extension
                "success_url": "https://haram-mute.com/checkout-success",
            }

            # Only add email if provided (Polar validates email domains strictly)
            if payload.email:
                checkout_data["customer_email"] = payload.email

            resp = await client.post(
                "https://api.polar.sh/v1/checkouts/",
                headers={
                    "Authorization": f"Bearer {settings.polar_api_key}",
                    "Content-Type": "application/json",
                },
                json=checkout_data,
                timeout=15.0,
            )

            if resp.status_code != 201:
                logger.error("Polar checkout creation failed: %s - %s", resp.status_code, resp.text)
                raise HTTPException(
                    status_code=502,
                    detail="Failed to create checkout session. Please try again.",
                )

            data = resp.json()
            checkout_url = data.get("url")
            checkout_id = data.get("id")

            if not checkout_url:
                logger.error("Polar checkout response missing URL: %s", data)
                raise HTTPException(
                    status_code=502,
                    detail="Invalid checkout response. Please try again.",
                )

            logger.info("Created Polar checkout for %s: %s", payload.email, checkout_id)
            return CreateCheckoutResponse(checkout_url=checkout_url, checkout_id=checkout_id)

    except httpx.TimeoutException:
        logger.error("Polar API timeout during checkout creation")
        raise HTTPException(
            status_code=504,
            detail="Payment service timeout. Please try again.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Polar checkout creation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to create checkout. Please try again.",
        )


@app.post("/customer-portal", response_model=CustomerPortalResponse)
async def create_customer_portal(payload: CustomerPortalRequest) -> CustomerPortalResponse:
    """Create a Polar customer portal session for subscription management."""
    if not _polar_configured():
        raise HTTPException(
            status_code=503,
            detail="Polar configuration is missing. Customer portal disabled.",
        )

    try:
        # Fetch subscription to get customer_id
        subscription = await _fetch_subscription_from_polar(payload.email)

        if not subscription.customer_id:
            raise HTTPException(status_code=403, detail="No customer found for email")

        # Create customer portal session
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(
                "https://api.polar.sh/v1/customer-sessions",
                headers={
                    "Authorization": f"Bearer {settings.polar_api_key}",
                    "Content-Type": "application/json",
                },
                json={"customer_id": subscription.customer_id},
                timeout=10.0,
            )

            if resp.status_code != 201:
                logger.error("Polar portal creation failed: %s - %s", resp.status_code, resp.text)
                raise HTTPException(
                    status_code=502,
                    detail="Failed to create customer portal session",
                )

            data = resp.json()
            portal_url = data.get("customer_portal_url")

            if not portal_url:
                logger.error("Polar portal response missing URL: %s", data)
                raise HTTPException(
                    status_code=502,
                    detail="Invalid portal response",
                )

            logger.info("Created customer portal for %s", payload.email)
            return CustomerPortalResponse(portal_url=portal_url)

    except httpx.TimeoutException:
        logger.error("Polar API timeout during portal creation")
        raise HTTPException(
            status_code=504,
            detail="Portal service timeout. Please try again.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Customer portal creation failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to create customer portal",
        )


# ---------------------------------------------------------------------------
# Polar Webhook Support - warm subscription cache on subscription events
# ---------------------------------------------------------------------------

async def _get_customer_email_from_polar(customer_id: str) -> str | None:
    """Fetch customer email from Polar API using customer_id."""
    if not customer_id:
        return None
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.polar.sh/v1/customers/{customer_id}",
                headers={"Authorization": f"Bearer {settings.polar_api_key}"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                email = resp.json().get("email")
                if email:
                    return normalize_email(email)
    except Exception as e:
        logger.warning("Failed to fetch customer email for %s: %s", customer_id, e)
    return None


async def _handle_subscription_webhook(event: dict) -> None:
    """Process subscription webhook event and update cache."""
    subscription = event.get("data", {})
    customer_id = subscription.get("customer_id")

    if not customer_id:
        logger.warning("Webhook missing customer_id: %s", event.get("type"))
        return

    # Fetch email from customer_id
    email = await _get_customer_email_from_polar(customer_id)
    if not email:
        logger.warning("Could not resolve email for customer %s", customer_id)
        return

    # Map status to cache record
    status = subscription.get("status", "")
    is_active = status in ("active", "trialing")

    record = SubscriptionCheckResponse(
        subscribed=is_active,
        customer_id=customer_id,
        plan=subscription.get("product", {}).get("name") if is_active else None,
        is_trial=(status == "trialing"),
        trial_ends_at=subscription.get("trial_ends_at"),
        reason=status if not is_active else None,
    )

    # Write to cache (reuse existing function)
    await run_sync(_write_subscription_cache, email, record)
    logger.info("Updated subscription cache for %s via webhook (status=%s)", email, status)


@app.post("/webhooks/polar")
async def polar_webhook(request: Request) -> dict:
    """
    Receive Polar subscription webhooks to warm the subscription cache.
    This eliminates the 20-second cold-cache delay for first-time users.
    """
    # Parse event from request body
    body = await request.body()
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in Polar webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type", "")
    logger.info("Received Polar webhook: %s", event_type)

    # Handle subscription events
    subscription_events = (
        "subscription.active",
        "subscription.updated",
        "subscription.canceled",
        "subscription.revoked",
        "subscription.past_due",
    )

    if event_type in subscription_events:
        try:
            await _handle_subscription_webhook(event)
        except Exception as e:
            # Log but don't fail - we want to return 200 to prevent Polar retries
            logger.exception("Error processing subscription webhook: %s", e)

    # Always return 200 to acknowledge receipt (prevents Polar retry storms)
    return {"status": "ok", "event": event_type}


@app.post("/api-keys/generate", response_model=ApiKeyGenerateResponse)
async def generate_api_key(payload: ApiKeyGenerateRequest, request: Request) -> ApiKeyGenerateResponse:
    _require_cloud_mode()
    email = normalize_email(payload.email)
    client_ip = request.client.host if request.client else "unknown"
    if not await run_sync(check_and_record_rate_limit, f"apikey:ip:{client_ip}", 1000):
        raise HTTPException(status_code=429, detail="Too many requests")
    if not await run_sync(check_and_record_rate_limit, f"apikey:email:{email}", 1000):
        raise HTTPException(status_code=429, detail="Too many requests")

    if not _polar_configured():
        if settings.local_mode or settings.dev_mode:
            record = await run_sync(get_or_create_api_key, email, None, "development")
            return ApiKeyGenerateResponse(
                api_key=record["api_key"],
                email=email,
                customer_id=None,
                plan="development",
                is_trial=False,
                trial_ends_at=None,
            )
        raise HTTPException(
            status_code=503,
            detail="Polar configuration is missing. API key issuance disabled.",
        )

    try:
        subscription = await _fetch_subscription_from_polar(email)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Payment service timeout. Please try again.",
        )

    if not subscription.subscribed:
        raise HTTPException(status_code=403, detail="No active subscription found")

    await run_sync(_write_subscription_cache, email, subscription)
    record = await run_sync(get_or_create_api_key, email, subscription.customer_id, "default")
    return ApiKeyGenerateResponse(
        api_key=record["api_key"],
        email=email,
        customer_id=subscription.customer_id,
        plan=subscription.plan,
        is_trial=subscription.is_trial,
        trial_ends_at=subscription.trial_ends_at,
    )


@app.post("/api-keys/revoke")
async def revoke_current_api_key(user: dict = Depends(_get_current_user)) -> dict:
    _require_cloud_mode()
    api_key = user.get("api_key")
    if api_key:
        await run_sync(revoke_api_key, api_key)
    return {"status": "revoked"}


@app.post("/api-keys/rotate")
async def rotate_current_api_key(user: dict = Depends(_get_current_user)) -> ApiKeyGenerateResponse:
    _require_cloud_mode()
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Missing email")
    record = await run_sync(rotate_api_key, email)
    return ApiKeyGenerateResponse(
        api_key=record["api_key"],
        email=record["email"],
        customer_id=record.get("customer_id"),
        plan=None,
        is_trial=False,
        trial_ends_at=None,
    )


@app.post("/jobs", response_model=JobStatusResponse, status_code=202)
async def create_job(payload: JobCreateRequest, user: dict = Depends(_get_current_user)) -> JobStatusResponse:
    await run_sync(_enforce_usage_limit, user)
    owner_email = normalize_email(user.get("email") or "")

    if settings.local_mode and not payload.skip_cache:
        active_job = await run_sync(
            job_store.find_active_job,
            str(payload.url),
            payload.stems,
            owner_email,
        )
        if active_job is not None:
            logger.info(
                "Reusing active local job %s for URL %s",
                active_job.job_id,
                payload.url,
            )
            return JobStatusResponse.from_job(active_job)

    # Check if we have a cached result for this URL (unless skip_cache is True)
    if not payload.skip_cache:
        # Reload volume to see completed jobs from other containers
        await run_sync(_reload_jobs_volume)
        cached_job = await run_sync(
            job_store.find_cached_job,
            str(payload.url),
            payload.stems,
            owner_email,
        )
        if cached_job:
            logger.info("Found cached job %s for URL %s", cached_job.job_id, payload.url)
            return JobStatusResponse.from_job(cached_job)
    else:
        logger.info("Skipping cache for URL %s (skip_cache=True)", payload.url)

    await run_sync(_enforce_jobs_rate_limit, owner_email)
    await run_sync(_enforce_concurrency_limits, owner_email)

    # Create new job
    job_id = uuid.uuid4().hex
    job = Job(
        job_id=job_id,
        source_url=str(payload.url),
        stems=payload.stems,
        owner_email=owner_email,
        message="Queued",
        progress=0.0,
    )
    created_new_job = True
    if settings.local_mode:
        try:
            job, created_new_job = await run_sync(
                job_store.admit_local_job,
                job,
                max_queued=MAX_QUEUED_JOBS,
                reuse_active=not payload.skip_cache,
            )
        except JobCapacityExceeded as exc:
            label = "pending" if exc.limit_kind == "queued" else "concurrent"
            raise HTTPException(
                status_code=429,
                detail=f"Too many {label} jobs (max {exc.limit})",
            ) from exc
        job_id = job.job_id
    else:
        await run_sync(job_store.create_job, job)

    if not created_new_job:
        logger.info(
            "Reusing concurrently-created active local job %s for URL %s",
            job_id,
            payload.url,
        )
        return JobStatusResponse.from_job(job)

    if settings.local_mode:
        source_provider = "youtube" if "youtube.com" in job.source_url or "youtu.be" in job.source_url else "other"
        _capture_local_desktop_event(
            "desktop_job_started",
            {
                "job_id": job_id,
                "stems": payload.stems,
                "source_provider": source_provider,
                "skip_cache": bool(payload.skip_cache),
            },
            event_key=f"job-started:{job_id}",
        )

    # Spawn worker function on Modal (fire-and-forget, Modal handles lifecycle)
    try:
        await run_sync(_spawn_job_worker, job_id, str(payload.url), payload.stems)
    except Exception as exc:
        if not settings.local_mode:
            raise
        internal_error = f"Local worker could not start: {type(exc).__name__}: {exc}"
        logger.exception("Local job %s could not start", job_id)
        failed_job = await run_sync(
            job_store.update_job,
            job_id,
            status=JobStatus.failed,
            message="Desktop processing runtime could not start",
            error_detail=internal_error,
            failure_stage="job_admission",
            failure_code="desktop_runtime_failed",
            failure_recoverable=False,
        )
        if failed_job is not None:
            job = failed_job
            _capture_local_worker_failure(job, exc, "job_admission")

    latest_job = await run_sync(job_store.get_job, job_id)
    if latest_job is not None:
        job = latest_job

    await run_sync(_cleanup_expired_jobs)
    return JobStatusResponse.from_job(job)


@app.get("/jobs/{job_id}", response_model=JobResultResponse)
async def get_job(job_id: str, user: dict = Depends(_get_current_user)) -> JobResultResponse:
    job = await run_sync(job_store.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _enforce_job_owner(job, user)

    # Reload volume to see files written by worker containers
    if job.status == JobStatus.completed:
        await run_sync(_reload_jobs_volume)

    download_url = None
    preview_url = None
    stems = []
    if job.stems_files:
        stems = sorted(job.stems_files.keys())
        preferred = 'vocals' if 'vocals' in job.stems_files else stems[0]
        preview_candidate = job.stems_files.get(preferred)
        if preview_candidate and preview_candidate.exists():
            preview_url = f"/jobs/{job.job_id}/stems/{preferred}"
    # Note: download_url (ZIP) is no longer generated - extension only uses preview_url
    # Keeping the endpoint for backward compatibility but it will always be None
    if job.status == JobStatus.completed and job.result_path and job.result_path.exists():
        download_url = f"/jobs/{job.job_id}/result"
    return JobResultResponse.from_job(job, download_url, preview_url, stems)


@app.get("/jobs/{job_id}/result")
async def download_result(job_id: str, user: dict = Depends(_get_current_user)) -> FileResponse:
    job = await run_sync(job_store.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _enforce_job_owner(job, user)
    if job.status != JobStatus.completed or not job.result_path:
        raise HTTPException(status_code=400, detail="Job is not ready")

    # Reload volume to see files written by worker containers
    await run_sync(_reload_jobs_volume)

    if not job.result_path.exists():
        raise HTTPException(status_code=410, detail="Result expired")
    return FileResponse(job.result_path, filename=f"{job.job_id}_stems.zip")


@app.get("/jobs/{job_id}/stems/{stem_name}")
async def download_stem(job_id: str, stem_name: str, user: dict = Depends(_get_current_user)) -> FileResponse:
    job = await run_sync(job_store.get_job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _enforce_job_owner(job, user)

    # Reload volume to see files written by worker containers
    await run_sync(_reload_jobs_volume)

    normalized = stem_name.lower()
    stem_path = job.stems_files.get(normalized)
    if not stem_path or not stem_path.exists():
        raise HTTPException(status_code=404, detail="Stem not found")
    # Return MP3 with streaming-friendly headers
    return FileResponse(stem_path, media_type="audio/mpeg")


@app.get("/jobs/{job_id}/chunks/{chunk_index}/vocals")
async def download_chunk(job_id: str, chunk_index: int, user: dict = Depends(_get_current_user)) -> FileResponse:
    """
    Download a specific chunk's vocals MP3 for progressive playback.
    This allows the extension to start playing as soon as the first chunk is ready.
    """
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _enforce_job_owner(job, user)

    # Check if chunking is enabled for this job
    if not job.chunking_enabled:
        raise HTTPException(status_code=400, detail="Job does not use chunked processing")

    # Validate chunk index
    if chunk_index < 0 or chunk_index >= len(job.chunks):
        raise HTTPException(status_code=404, detail="Chunk index out of range")

    # Check if chunk is ready
    chunk_data = job.chunks[chunk_index]
    if chunk_data.get('status') != 'completed' or not chunk_data.get('file_ready'):
        raise HTTPException(status_code=202, detail="Chunk not yet ready")

    # Reload volume to see files written by worker containers
    _reload_jobs_volume()

    # Get chunk file path
    chunk_path = job.chunk_files.get(chunk_index)
    if not chunk_path or not chunk_path.exists():
        # Try the expected path pattern
        result_dir = settings.data_dir / "jobs" / job_id / "result"
        chunk_path = result_dir / f"vocals_chunk_{chunk_index}.mp3"
        if not chunk_path.exists():
            raise HTTPException(status_code=202, detail="Chunk file not yet visible")

    return FileResponse(chunk_path, media_type="audio/mpeg")


def _cleanup_expired_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.keep_hours)
    for job_id in job_store.expired_job_ids(cutoff):
        job_dir = job_store.job_dir(job_id)
        try:
            _remove_path(job_dir)
        except OSError:
            logger.warning("Failed to remove %s", job_dir)
    # Commit volume changes after cleanup to persist deletions
    _commit_volume_if_modal()


def _remove_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        for child in path.iterdir():
            _remove_path(child)
        path.rmdir()
    else:
        path.unlink(missing_ok=True)


def _commit_volume_if_modal() -> None:
    """Commit volume changes if running on Modal to ensure persistence."""
    try:
        # Check if we're running on Modal by looking for the modal module
        import modal

        # Attempt to get and commit the volume
        vol = modal.Volume.from_name("music-remover-chunked-jobs", create_if_missing=False)
        if vol:
            vol.commit()
            logger.debug("Successfully committed Modal volume changes")
    except (ImportError, Exception) as e:
        # Not on Modal or commit failed - this is fine for local development
        logger.debug("Volume commit skipped (not on Modal or failed): %s", e)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8765)


__all__ = ["app"]
