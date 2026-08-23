"""Durable, privacy-safe telemetry for the packaged desktop application.

This module is inert until the tray launcher explicitly configures it. Events are
written to a small local outbox before a daemon thread attempts delivery, so
analytics can never block or fail a processing job.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger(__name__)

POSTHOG_API_KEY = "phc_S3oxtwRca6jTbCpeSUdSULFZRSQo85ujNkips64sH67"
POSTHOG_BATCH_URL = "https://us.i.posthog.com/batch/"
OUTBOX_MAX_BYTES = 1_000_000
OUTBOX_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
SEND_BATCH_SIZE = 50
SEND_TIMEOUT_SECONDS = 3.0

_URL_RE = re.compile(r"https?://[^\s\]\[\)\(]+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_WINDOWS_USER_RE = re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\\s]+")
_UNIX_USER_RE = re.compile(r"(?i)(?<!\w)/(?:Users|home)/[^/\s]+")
_YOUTUBE_ID_RE = re.compile(r"(?i)(\[youtube\]\s+)[A-Za-z0-9_-]{6,}")


@dataclass(frozen=True)
class _TelemetryConfig:
    install_id: str
    boot_id: str
    context: dict[str, Any]
    outbox_dir: Path


_config: Optional[_TelemetryConfig] = None
_config_lock = threading.RLock()
_send_wakeup = threading.Event()
_sender_thread: Optional[threading.Thread] = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enabled_by_environment() -> bool:
    # Linux build ships telemetry OFF by default; opt in with
    # HARAMMUTE_TELEMETRY_ENABLED=1.
    value = os.environ.get("HARAMMUTE_TELEMETRY_ENABLED", "0")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _load_or_create_install_id(telemetry_dir: Path) -> str:
    install_id_path = telemetry_dir / "install_id"
    try:
        existing = install_id_path.read_text(encoding="utf-8").strip()
        if existing:
            return str(uuid.UUID(existing))
    except (OSError, ValueError):
        pass

    install_id = str(uuid.uuid4())
    _atomic_write_text(install_id_path, install_id)
    return install_id


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:1_000]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)[:1_000]


def sanitize_error_summary(error: Any, limit: int = 400) -> str:
    """Return a bounded error summary without URLs, emails, or user folders."""
    text = str(error or "unclassified")
    text = _URL_RE.sub("<url>", text)
    text = _EMAIL_RE.sub("<email>", text)
    text = _WINDOWS_USER_RE.sub(r"C:\\Users\\<user>", text)
    text = _UNIX_USER_RE.sub("/Users/<user>", text)
    text = _YOUTUBE_ID_RE.sub(r"\1<video_id>", text)
    text = " ".join(text.split())
    return text[:limit]


def error_fingerprint(error_summary: str) -> str:
    normalized = re.sub(r"\b\d+(?:\.\d+)?\b", "#", error_summary.lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _prune_outbox(config: _TelemetryConfig) -> None:
    try:
        files = sorted(
            config.outbox_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
        )
    except OSError:
        return

    cutoff = time.time() - OUTBOX_MAX_AGE_SECONDS
    retained: list[tuple[Path, int]] = []
    for path in files:
        try:
            stat = path.stat()
            if stat.st_mtime < cutoff:
                path.unlink(missing_ok=True)
                continue
            retained.append((path, stat.st_size))
        except OSError:
            continue

    total_bytes = sum(size for _path, size in retained)
    for path, size in retained:
        if total_bytes <= OUTBOX_MAX_BYTES:
            break
        try:
            path.unlink(missing_ok=True)
            total_bytes -= size
        except OSError:
            continue


def configure_desktop_telemetry(
    data_dir: Path,
    *,
    boot_id: str,
    context: Optional[dict[str, Any]] = None,
    enabled: bool = True,
) -> bool:
    """Configure desktop telemetry once. Returns False when explicitly disabled."""
    global _config, _sender_thread

    if not enabled or not _enabled_by_environment():
        with _config_lock:
            _config = None
        logger.info("Desktop telemetry is disabled")
        return False

    try:
        telemetry_dir = Path(data_dir) / "telemetry"
        outbox_dir = telemetry_dir / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)
        install_id = _load_or_create_install_id(telemetry_dir)
        config = _TelemetryConfig(
            install_id=install_id,
            boot_id=str(boot_id),
            context=_json_safe(context or {}),
            outbox_dir=outbox_dir,
        )
        with _config_lock:
            _config = config
            if _sender_thread is None or not _sender_thread.is_alive():
                _sender_thread = threading.Thread(
                    target=_sender_loop,
                    name="harammute-telemetry",
                    daemon=True,
                )
                _sender_thread.start()
        _prune_outbox(config)
        _send_wakeup.set()
        return True
    except Exception as exc:
        logger.debug("Desktop telemetry configuration failed: %s", exc)
        return False


def capture_desktop_event(
    event_name: str,
    properties: Optional[dict[str, Any]] = None,
    *,
    event_key: str,
) -> bool:
    """Persist one event for asynchronous delivery. Never raises to the caller."""
    try:
        with _config_lock:
            config = _config
        if config is None:
            return False

        event_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"harammute-desktop:{config.install_id}:{event_key}",
            )
        )
        common = {
            "distinct_id": f"harammute-desktop:{config.install_id}",
            "$process_person_profile": False,
            "$lib": "harammute-desktop",
            "telemetry_source": "desktop_app",
            "telemetry_schema_version": 1,
            "event_id": event_id,
            "desktop_install_id": config.install_id,
            "desktop_boot_id": config.boot_id,
            **config.context,
        }
        common.update(_json_safe(properties or {}))
        event = {
            "event": str(event_name),
            "uuid": event_id,
            "timestamp": _utc_now(),
            "properties": common,
        }
        event_path = config.outbox_dir / f"{event_id}.json"
        _atomic_write_text(event_path, json.dumps(event, separators=(",", ":")))
        _prune_outbox(config)
        _send_wakeup.set()
        return True
    except Exception as exc:
        logger.debug("Desktop telemetry capture failed for %s: %s", event_name, exc)
        return False


def _post_batch(events: list[dict[str, Any]]) -> None:
    payload = json.dumps({"api_key": POSTHOG_API_KEY, "batch": events}).encode("utf-8")
    request = urllib.request.Request(
        POSTHOG_BATCH_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "HaramMute-Desktop-Telemetry/1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=SEND_TIMEOUT_SECONDS) as response:
        status = int(getattr(response, "status", response.getcode()))
        if not 200 <= status < 300:
            raise OSError(f"PostHog returned HTTP {status}")


def flush_desktop_telemetry_once() -> bool:
    """Attempt one outbox batch. Returns True only when a batch was delivered."""
    with _config_lock:
        config = _config
    if config is None:
        return False

    valid_paths: list[Path] = []
    try:
        paths = sorted(
            config.outbox_dir.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
        )[:SEND_BATCH_SIZE]
        if not paths:
            return False
        events = []
        for path in paths:
            try:
                events.append(json.loads(path.read_text(encoding="utf-8")))
                valid_paths.append(path)
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("Dropping unreadable desktop telemetry event %s: %s", path.name, exc)
                path.unlink(missing_ok=True)
        if not events:
            return False
        _post_batch(events)
        for path in valid_paths:
            path.unlink(missing_ok=True)
        return True
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code not in {408, 429}:
            logger.warning("Dropping rejected desktop telemetry batch after HTTP %d", exc.code)
            for path in valid_paths:
                path.unlink(missing_ok=True)
            return True
        logger.debug("Desktop telemetry delivery deferred: %s", exc)
        return False
    except Exception as exc:
        logger.debug("Desktop telemetry delivery deferred: %s", exc)
        return False


def _sender_loop() -> None:
    retry_delay = 5.0
    while True:
        _send_wakeup.wait(timeout=30.0)
        _send_wakeup.clear()
        while flush_desktop_telemetry_once():
            retry_delay = 5.0
        with _config_lock:
            config = _config
        if config is not None and any(config.outbox_dir.glob("*.json")):
            _send_wakeup.wait(timeout=retry_delay)
            retry_delay = min(300.0, retry_delay * 2)


def _reset_desktop_telemetry_for_tests() -> None:
    """Reset configuration for isolated unit tests."""
    global _config
    with _config_lock:
        _config = None
    _send_wakeup.clear()
