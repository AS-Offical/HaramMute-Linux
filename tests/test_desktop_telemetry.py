import json
from pathlib import Path

import pytest

from app import desktop_telemetry as telemetry


@pytest.fixture(autouse=True)
def reset_telemetry_state():
    telemetry._reset_desktop_telemetry_for_tests()
    yield
    telemetry._reset_desktop_telemetry_for_tests()


def configure_outbox(path: Path) -> None:
    outbox = path / "outbox"
    outbox.mkdir(parents=True)
    telemetry._config = telemetry._TelemetryConfig(
        install_id="00000000-0000-4000-8000-000000000001",
        boot_id="test-boot",
        context={"app_version": "test"},
        outbox_dir=outbox,
    )


def test_error_summary_redacts_sensitive_parts_and_limits_length() -> None:
    summary = telemetry.sanitize_error_summary(
        "Failed https://example.com/path for person@example.com [youtube] dQw4w9WgXcQ"
    )

    assert "https://example.com" not in summary
    assert "person@example.com" not in summary
    assert "dQw4w9WgXcQ" not in summary
    assert "<url>" in summary
    assert "<email>" in summary
    assert len(telemetry.sanitize_error_summary("x" * 500, limit=20)) == 20


def test_error_fingerprint_ignores_numbers() -> None:
    assert telemetry.error_fingerprint("worker failed after 12 seconds") == telemetry.error_fingerprint(
        "worker failed after 30 seconds"
    )


def test_capture_returns_false_when_telemetry_is_unconfigured(tmp_path: Path) -> None:
    telemetry._reset_desktop_telemetry_for_tests()

    assert telemetry.capture_desktop_event("job_started", event_key="job:1") is False


def test_capture_persists_deterministic_privacy_limited_event(tmp_path: Path) -> None:
    configure_outbox(tmp_path)

    assert telemetry.capture_desktop_event(
        "job_failed", {"attempt": 2, "path": tmp_path / "file.wav"}, event_key="job:stable"
    )
    assert telemetry.capture_desktop_event(
        "job_failed", {"attempt": 2, "path": tmp_path / "file.wav"}, event_key="job:stable"
    )

    files = list((tmp_path / "outbox").glob("*.json"))
    assert len(files) == 1
    event = json.loads(files[0].read_text(encoding="utf-8"))
    assert event["event"] == "job_failed"
    assert event["properties"]["desktop_boot_id"] == "test-boot"
    assert event["properties"]["path"] == str(tmp_path / "file.wav")
    assert event["properties"]["attempt"] == 2


def test_flush_removes_delivered_events(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    telemetry.capture_desktop_event("job_started", event_key="job:2")
    monkeypatch.setattr(telemetry, "_post_batch", lambda events: None)

    assert telemetry.flush_desktop_telemetry_once() is True
    assert list((tmp_path / "outbox").glob("*.json")) == []


def test_flush_keeps_events_when_delivery_is_deferred(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    telemetry.capture_desktop_event("job_started", event_key="job:3")

    def fail_delivery(_events):
        raise OSError("offline")

    monkeypatch.setattr(telemetry, "_post_batch", fail_delivery)

    assert telemetry.flush_desktop_telemetry_once() is False
    assert len(list((tmp_path / "outbox").glob("*.json"))) == 1
