#!/usr/bin/env python3
"""HaramMute Linux system-tray launcher (AppIndicator/SNI).

Shows a panel icon compatible with modern XFCE/GNOME status-notifier panels.
Runs on the SYSTEM python3 (needs gir1.2-ayatanaappindicator3-0.1); spawns the
local server unless one is already listening on the port.
"""

import argparse
import json
import fcntl
import os
import signal
import shutil
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3
except (ImportError, ValueError):
    # openSUSE still ships the compatible AppIndicator3 typelib in its base repos.
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AyatanaAppIndicator3

ROOT = Path(__file__).resolve().parent
ICON_PATH = ROOT / "icon.png"


def server_running(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with urlopen(f"http://{host}:{port}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return (
                response.status == 200
                and payload.get("status") == "ok"
                and payload.get("service") == "harammute"
                and payload.get("version", "").endswith("-linux")
            )
    except (OSError, ValueError, URLError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.host != "127.0.0.1":
        raise SystemExit("The extension contract requires the local server at 127.0.0.1.")

    termination_requested = threading.Event()

    def capture_early_shutdown(_signum, _frame):
        termination_requested.set()

    # Install handlers before starting the child, so an early stop cannot leave
    # the server orphaned while GTK and the indicator are still initializing.
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, capture_early_shutdown)

    state_dir = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    lock_file = (state_dir / f"harammute-tray-{os.getuid()}.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("HaramMute tray is already running.", flush=True)
        return

    url = f"http://{args.host}:{args.port}"
    server = None
    owns_server = False
    restart_attempts = 0
    restart_after = 0.0
    health_failures = 0
    log_handle = None
    if not server_running(args.host, args.port):
        data_dir = Path(
            os.environ.get("MUSIC_REMOVER_DATA_DIR")
            or os.environ.get("HARAMMUTE_DATA_DIR")
            or Path.home() / ".local/share/HaramMute"
        ).expanduser()
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_handle = (log_dir / "server.log").open("a", encoding="utf-8")
        server_env = os.environ.copy()
        bundled_python = ROOT / "python-runtime" / "bin" / "python3.12"
        if bundled_python.is_file():
            server_env["HARAMMUTE_PYTHON_BINARY"] = str(bundled_python)
            server_env["PYTHONPATH"] = os.pathsep.join(
                filter(None, [str(ROOT / "python-packages"), str(ROOT), server_env.get("PYTHONPATH")])
            )
            server_env["PATH"] = os.pathsep.join([str(ROOT / "bin"), server_env.get("PATH", "")])
            if (ROOT / "bin" / "ffmpeg").is_file():
                server_env["MUSIC_REMOVER_FFMPEG_BINARY"] = str(ROOT / "bin" / "ffmpeg")
            if (ROOT / "bin" / "ffprobe").is_file():
                server_env["MUSIC_REMOVER_FFPROBE_BINARY"] = str(ROOT / "bin" / "ffprobe")
        server = subprocess.Popen(
            [str(ROOT / "harammute-server"), "--host", args.host, "--port", str(args.port)],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=server_env,
        )
        owns_server = True
        for _ in range(60):
            if termination_requested.is_set():
                if server.poll() is None:
                    server.terminate()
                    try:
                        server.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait()
                if log_handle:
                    log_handle.close()
                return
            if server.poll() is not None:
                log_handle.close()
                raise SystemExit(f"HaramMute server exited during startup. See {log_dir / 'server.log'}")
            if server_running(args.host, args.port):
                break
            time.sleep(0.5)
        else:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            log_handle.close()
            raise SystemExit(f"HaramMute server did not become healthy. See {log_dir / 'server.log'}")

    managed_by_systemd = (
        subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "harammute"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
        if shutil.which("systemctl")
        else False
    )

    indicator = AyatanaAppIndicator3.Indicator.new(
        "harammute",
        str(ICON_PATH),
        AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
    if not ICON_PATH.exists():
        indicator.set_label("HM", "")

    def open_browser(_source):
        subprocess.Popen(["xdg-open", url])

    def quit_app(_source):
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        if log_handle:
            log_handle.close()
        Gtk.main_quit()

    def supervise_server():
        nonlocal server, restart_attempts, restart_after, health_failures
        if not owns_server:
            return GLib.SOURCE_CONTINUE
        if server is not None and server.poll() is None:
            # A slow health response can happen while the audio model is busy.
            # Never kill a live server for a missed probe: doing so interrupts
            # the active job and makes the extension appear disconnected.
            if server_running(args.host, args.port, timeout=0.5):
                health_failures = 0
                restart_attempts = 0
                indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
                return GLib.SOURCE_CONTINUE
            health_failures += 1
            if health_failures >= 2:
                indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ATTENTION)
            return GLib.SOURCE_CONTINUE
        if time.monotonic() < restart_after:
            return GLib.SOURCE_CONTINUE
        if restart_attempts >= 5:
            indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ATTENTION)
            return GLib.SOURCE_CONTINUE
        restart_attempts += 1
        restart_after = time.monotonic() + min(2 ** restart_attempts, 30)
        if log_handle:
            log_handle.write(f"\n[tray] Restarting server (attempt {restart_attempts}/5)\n")
            log_handle.flush()
        server = subprocess.Popen(
            [str(ROOT / "harammute-server"), "--host", args.host, "--port", str(args.port)],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=server_env,
        )
        indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        return GLib.SOURCE_CONTINUE

    GLib.timeout_add_seconds(5, supervise_server)

    menu = Gtk.Menu()
    for label, callback, default in (
        ("افتح في المتصفح", open_browser, True),
        ("إيقاف HaramMute" if owns_server or managed_by_systemd else "إغلاق أيقونة Tray", quit_app, False),
    ):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", callback)
        item.show()
        menu.append(item)

    indicator.set_menu(menu)

    def shutdown(_user_data=None):
        quit_app(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, shutdown, None)

    if termination_requested.is_set():
        quit_app(None)
        return

    print(f"HaramMute tray active: {url}", flush=True)
    Gtk.main()


if __name__ == "__main__":
    sys.exit(main())
