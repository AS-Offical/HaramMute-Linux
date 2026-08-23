#!/usr/bin/env python3
"""HaramMute Linux system-tray launcher (AppIndicator/SNI).

Shows a panel icon compatible with modern XFCE/GNOME status-notifier panels.
Runs on the SYSTEM python3 (needs gir1.2-ayatanaappindicator3-0.1); spawns the
local server unless one is already listening on the port.
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3, GLib, Gtk

ROOT = Path(__file__).resolve().parent
ICON_PATH = ROOT / "icon.png"


def server_running(host: str, port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1.5)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    server = None
    if not server_running(args.host, args.port):
        server = subprocess.Popen(
            [str(ROOT / "harammute"), "--host", args.host, "--port", str(args.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
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
        Gtk.main_quit()

    menu = Gtk.Menu()
    for label, callback, default in (
        ("افتح في المتصفح", open_browser, True),
        ("إيقاف HaramMute", quit_app, False),
    ):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", callback)
        item.show()
        menu.append(item)

    indicator.set_menu(menu)

    def shutdown(_signum, _frame):
        quit_app(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, shutdown, None)

    print(f"HaramMute tray active: {url}", flush=True)
    Gtk.main()


if __name__ == "__main__":
    sys.exit(main())
