import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

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


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_telemetry_enablement_accepts_supported_values(monkeypatch, value: str) -> None:
    monkeypatch.setenv("HARAMMUTE_TELEMETRY_ENABLED", value)
    assert telemetry._enabled_by_environment() is True


def test_telemetry_enablement_is_off_by_default_and_for_other_values(monkeypatch) -> None:
    monkeypatch.delenv("HARAMMUTE_TELEMETRY_ENABLED", raising=False)
    assert telemetry._enabled_by_environment() is False
    monkeypatch.setenv("HARAMMUTE_TELEMETRY_ENABLED", "enabled")
    assert telemetry._enabled_by_environment() is False


def test_load_install_id_reuses_valid_id_and_replaces_invalid_file(tmp_path: Path) -> None:
    install_id_path = tmp_path / "install_id"
    install_id_path.write_text("00000000-0000-4000-8000-000000000002", encoding="utf-8")
    assert telemetry._load_or_create_install_id(tmp_path) == install_id_path.read_text().strip()

    install_id_path.write_text("invalid", encoding="utf-8")
    generated = telemetry._load_or_create_install_id(tmp_path)
    assert len(generated) == 36
    assert install_id_path.read_text(encoding="utf-8") == generated


def test_json_safe_handles_nested_values_and_truncates_strings(tmp_path: Path) -> None:
    assert telemetry._json_safe(None) is None
    assert telemetry._json_safe(4) == 4
    assert telemetry._json_safe("x" * 1001) == "x" * 1000
    assert telemetry._json_safe(tmp_path) == str(tmp_path)
    assert telemetry._json_safe({1: [True, {"value": 2}]}) == {"1": [True, {"value": 2}]}
    assert telemetry._json_safe(object())


def test_prune_outbox_removes_expired_and_oldest_oversize_files(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    old = tmp_path / "outbox" / "old.json"
    recent = tmp_path / "outbox" / "recent.json"
    old.write_text("1234", encoding="utf-8")
    recent.write_text("5678", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - telemetry.OUTBOX_MAX_AGE_SECONDS - 10, now - telemetry.OUTBOX_MAX_AGE_SECONDS - 10))
    os.utime(recent, (now - 2, now - 2))

    telemetry._prune_outbox(telemetry._config)
    assert not old.exists()

    monkeypatch.setattr(telemetry, "OUTBOX_MAX_BYTES", 4)
    telemetry._prune_outbox(telemetry._config)
    assert recent.exists()

    newer = tmp_path / "outbox" / "newer.json"
    newer.write_text("abcd", encoding="utf-8")
    os.utime(recent, (now - 3, now - 3))
    os.utime(newer, (now - 1, now - 1))
    telemetry._prune_outbox(telemetry._config)
    assert not recent.exists()
    assert newer.exists()


def test_prune_outbox_tolerates_directory_stat_and_unlink_errors(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    outbox = tmp_path / "outbox"
    first = outbox / "first.json"
    second = outbox / "second.json"
    first.write_text("1234", encoding="utf-8")
    second.write_text("5678", encoding="utf-8")
    now = time.time()
    os.utime(first, (now - 2, now - 2))
    os.utime(second, (now - 1, now - 1))
    original_unlink = Path.unlink

    def fail_first_unlink(path, *args, **kwargs):
        if path == first:
            raise OSError("busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_first_unlink)
    monkeypatch.setattr(telemetry, "OUTBOX_MAX_BYTES", 4)
    telemetry._prune_outbox(telemetry._config)
    assert first.exists()
    assert not second.exists()


def test_prune_outbox_returns_if_globbing_fails(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    original_glob = Path.glob

    def fail_outbox_glob(path, pattern):
        if path == telemetry._config.outbox_dir:
            raise OSError("unavailable")
        return original_glob(path, pattern)

    monkeypatch.setattr(Path, "glob", fail_outbox_glob)
    telemetry._prune_outbox(telemetry._config)


def test_prune_outbox_skips_files_whose_stat_fails(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    event_path = tmp_path / "outbox" / "event.json"
    event_path.write_text("{}", encoding="utf-8")
    original_stat = Path.stat
    calls = 0

    def fail_second_stat(path, *args, **kwargs):
        nonlocal calls
        if path == event_path:
            calls += 1
            if calls == 2:
                raise OSError("disappeared")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_second_stat)
    telemetry._prune_outbox(telemetry._config)


def test_configure_desktop_telemetry_respects_opt_in_without_starting_thread(monkeypatch, tmp_path: Path) -> None:
    class FakeThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False

        def is_alive(self):
            return False

        def start(self):
            self.started = True

    monkeypatch.setenv("HARAMMUTE_TELEMETRY_ENABLED", "yes")
    monkeypatch.setattr(telemetry.threading, "Thread", FakeThread)
    monkeypatch.setattr(telemetry, "_sender_thread", None)

    assert telemetry.configure_desktop_telemetry(tmp_path, boot_id="boot-1", context={"n": 1})
    assert telemetry._config.boot_id == "boot-1"
    assert telemetry._config.context == {"n": 1}
    assert telemetry._sender_thread.started


def test_configure_desktop_telemetry_returns_false_if_setup_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HARAMMUTE_TELEMETRY_ENABLED", "1")
    monkeypatch.setattr(Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("denied")))

    assert telemetry.configure_desktop_telemetry(tmp_path, boot_id="boot") is False


def test_configure_desktop_telemetry_can_be_disabled_explicitly(tmp_path: Path) -> None:
    assert telemetry.configure_desktop_telemetry(tmp_path, boot_id="boot", enabled=False) is False
    assert telemetry._config is None


def test_capture_returns_false_when_atomic_write_fails(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    monkeypatch.setattr(telemetry, "_atomic_write_text", lambda *args: (_ for _ in ()).throw(OSError("disk")))

    assert telemetry.capture_desktop_event("job_failed", event_key="disk-error") is False


def test_post_batch_sends_json_and_rejects_http_error_status(monkeypatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def getcode(self):
            return self.status

    requests = []
    def fake_urlopen(request: Request, timeout: float):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(telemetry.urllib.request, "urlopen", fake_urlopen)
    telemetry._post_batch([{"event": "ok"}])
    request, timeout = requests[0]
    assert request.method == "POST"
    assert json.loads(request.data)["batch"] == [{"event": "ok"}]
    assert timeout == telemetry.SEND_TIMEOUT_SECONDS

    Response.status = 500
    with pytest.raises(OSError, match="HTTP 500"):
        telemetry._post_batch([])


def test_flush_returns_false_when_unconfigured_or_empty(tmp_path: Path) -> None:
    assert telemetry.flush_desktop_telemetry_once() is False
    configure_outbox(tmp_path)
    assert telemetry.flush_desktop_telemetry_once() is False


def test_flush_discards_invalid_records_and_succeeds_if_valid_records_remain(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    outbox = tmp_path / "outbox"
    (outbox / "broken.json").write_text("{bad", encoding="utf-8")
    (outbox / "valid.json").write_text('{"event":"valid"}', encoding="utf-8")
    monkeypatch.setattr(telemetry, "_post_batch", lambda events: None)

    assert telemetry.flush_desktop_telemetry_once() is True
    assert not (outbox / "broken.json").exists()
    assert not (outbox / "valid.json").exists()


def test_flush_returns_false_if_all_records_are_invalid(tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    (tmp_path / "outbox" / "broken.json").write_text("{bad", encoding="utf-8")

    assert telemetry.flush_desktop_telemetry_once() is False
    assert list((tmp_path / "outbox").glob("*.json")) == []


@pytest.mark.parametrize("status,expected", [(400, True), (408, False), (429, False), (500, False)])
def test_flush_http_failures_drop_only_permanent_client_errors(
    monkeypatch, tmp_path: Path, status: int, expected: bool
) -> None:
    configure_outbox(tmp_path)
    telemetry.capture_desktop_event("job", event_key=f"http-{status}")

    def reject(_events):
        raise HTTPError("https://example.test", status, "rejected", None, None)

    monkeypatch.setattr(telemetry, "_post_batch", reject)
    assert telemetry.flush_desktop_telemetry_once() is expected
    assert bool(list((tmp_path / "outbox").glob("*.json"))) is (not expected)


def test_sender_loop_flushes_batches_and_waits_before_retry(monkeypatch, tmp_path: Path) -> None:
    configure_outbox(tmp_path)
    (tmp_path / "outbox" / "pending.json").write_text("{}", encoding="utf-8")

    class StopLoop(Exception):
        pass

    class FakeWakeup:
        def __init__(self):
            self.waits = []

        def wait(self, timeout=None):
            self.waits.append(timeout)
            if len(self.waits) == 3:
                raise StopLoop

        def clear(self):
            pass

    wakeup = FakeWakeup()
    flush_results = iter([True, False])
    monkeypatch.setattr(telemetry, "_send_wakeup", wakeup)
    monkeypatch.setattr(telemetry, "flush_desktop_telemetry_once", lambda: next(flush_results))

    with pytest.raises(StopLoop):
        telemetry._sender_loop()

    assert wakeup.waits == [30.0, 5.0, 30.0]
