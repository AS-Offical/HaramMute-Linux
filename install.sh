#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
PYTHON="${PYTHON:-}"
ACCELERATION="${HARAMMUTE_ACCELERATION:-cpu}"
DATA_DIR="${MUSIC_REMOVER_DATA_DIR:-${HARAMMUTE_DATA_DIR:-$HOME/.local/share/HaramMute}}"
FORCE_MANAGED_PYTHON=0

while (($#)); do
    case "$1" in
        --acceleration)
            [[ $# -ge 2 ]] || { echo "--acceleration needs cpu|nvidia|intel|amd" >&2; exit 2; }
            ACCELERATION="$2"; shift 2 ;;
        --managed-python)
            FORCE_MANAGED_PYTHON=1; shift ;;
        --help|-h)
            echo "Usage: ./install.sh [--acceleration cpu|nvidia|intel|amd] [--managed-python]"
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
case "$ACCELERATION" in cpu|nvidia|intel|amd) ;; *) echo "Unsupported acceleration: $ACCELERATION" >&2; exit 2 ;; esac

echo "=== HaramMute Linux Setup ==="

if [[ "$EUID" -eq 0 && -n "${SUDO_USER:-}" ]]; then
    echo "Run ./install.sh as your normal user; it will request sudo only for system packages." >&2
    exit 2
fi

if [[ -e /etc/alpine-release ]] || ldd --version 2>&1 | grep -qi musl; then
    echo "This PyTorch/ONNX Runtime stack requires glibc and has no supported musl setup. Use a glibc-based Linux distribution." >&2
    exit 1
fi

run_as_root() {
    if [[ "$EUID" -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

if [[ -z "$PYTHON" && "$FORCE_MANAGED_PYTHON" -eq 0 ]]; then
    for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && \
            "$candidate" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' 2>/dev/null; then
            PYTHON="$(command -v "$candidate")"
            break
        fi
    done
fi

install_system_dependencies() {
    local packages=()
    local distro_id="${ID:-}"
    local distro_ids=" $distro_id ${ID_LIKE:-} "
    if [[ "$EUID" -ne 0 ]] && ! command -v sudo >/dev/null 2>&1; then
        echo "Install ffmpeg/ffprobe, curl, and the optional GTK/Ayatana tray dependencies with your package manager, then rerun with HARAMMUTE_SKIP_SYSTEM_DEPS=1." >&2
        exit 1
    fi
    case "$distro_ids" in
        *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*)
            if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then packages+=(ffmpeg); fi
            packages+=(python3-venv xdg-utils curl ca-certificates python3-gi gir1.2-ayatanaappindicator3-0.1)
            if ! command -v sudo >/dev/null && [[ "$EUID" -ne 0 ]]; then
                echo "Install these system packages, then rerun: ffmpeg python3-venv xdg-utils python3-gi gir1.2-ayatanaappindicator3-0.1" >&2
                exit 1
            fi
            if ((${#packages[@]})); then
                run_as_root apt-get install -y "${packages[@]}"
            fi
            ;;
        *" fedora "*)
            # Fedora ships the codec-limited implementation in its official
            # repositories under this name (the executables are still ffmpeg
            # and ffprobe). The unqualified RPM is commonly provided by a
            # third-party repository.
            if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then packages+=(ffmpeg-free); fi
            packages+=(python3-gobject xdg-utils curl ca-certificates libayatana-appindicator-gtk3)
            if ((${#packages[@]})); then run_as_root dnf install -y "${packages[@]}"; fi
            ;;
        *" arch "*|*" manjaro "*|*" cachyos "*|*" endeavouros "*)
            if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then packages+=(ffmpeg); fi
            packages+=(python-gobject xdg-utils curl ca-certificates libayatana-appindicator)
            if ((${#packages[@]})); then run_as_root pacman -S --needed --noconfirm "${packages[@]}"; fi
            ;;
        *opensuse*|*suse*)
            if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then packages+=(ffmpeg); fi
            packages+=(python3-gobject typelib-1_0-Gtk-3_0 typelib-1_0-AppIndicator3-0_1 xdg-utils curl ca-certificates)
            if ((${#packages[@]})); then run_as_root zypper --non-interactive install "${packages[@]}"; fi
            ;;
        *" gentoo "*)
            if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then packages+=(media-video/ffmpeg); fi
            packages+=(dev-python/pygobject dev-libs/libayatana-appindicator x11-libs/gtk+ net-misc/curl app-misc/ca-certificates x11-misc/xdg-utils)
            if ((${#packages[@]})); then run_as_root emerge --ask=n "${packages[@]}"; fi
            ;;
        *" alpine "*|alpine*)
            echo "Alpine uses musl; the pinned PyTorch/ONNX wheel stack currently targets glibc Linux. Use a glibc-based distro or a glibc container for HaramMute." >&2
            exit 1
            ;;
        *)
            echo "No automatic dependency recipe exists for ${ID:-this distribution}. Checking installed runtime dependencies." >&2
            ;;
    esac
}

check_runtime_dependencies() {
    local missing=()
    command -v ffmpeg >/dev/null 2>&1 || missing+=(ffmpeg)
    command -v ffprobe >/dev/null 2>&1 || missing+=(ffprobe)
    command -v curl >/dev/null 2>&1 || missing+=(curl)
    command -v xdg-open >/dev/null 2>&1 || missing+=(xdg-utils)
    command -v python3 >/dev/null 2>&1 || missing+=(python3)
    if command -v python3 >/dev/null 2>&1 && ! python3 -c '
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
for namespace in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(namespace, "0.1")
        repository = __import__("gi.repository", fromlist=[namespace])
        getattr(repository, namespace)
        break
    except (ImportError, ValueError):
        continue
else:
    raise SystemExit(1)
' >/dev/null 2>&1; then
        missing+=("Python GTK3/AppIndicator bindings")
    fi
    if ((${#missing[@]})); then
        printf 'Missing required runtime dependencies: %s\n' "${missing[*]}" >&2
        echo "Install the listed packages with your distribution package manager, then rerun ./install.sh." >&2
        exit 1
    fi
}

if [[ "${HARAMMUTE_SKIP_SYSTEM_DEPS:-0}" != 1 ]]; then
    . /etc/os-release
    install_system_dependencies
fi
check_runtime_dependencies

# The pinned audio stack does not yet support Python 3.13+. Use a managed,
# user-local Python 3.12 when requested or when the host only ships a newer one.
if [[ -z "$PYTHON" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
        echo "Python 3.10–3.12 was not found and curl is required to install a managed Python runtime." >&2
        exit 1
    fi
    UV_BIN="$(command -v uv || true)"
    if [[ -z "$UV_BIN" && -x "$HOME/.local/bin/uv" ]]; then UV_BIN="$HOME/.local/bin/uv"; fi
    if [[ -z "$UV_BIN" ]]; then
        echo "Installing uv to manage the compatible Python runtime..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        UV_BIN="$HOME/.local/bin/uv"
    fi
    export UV_PYTHON_INSTALL_DIR="$DATA_DIR/python"
    mkdir -p "$UV_PYTHON_INSTALL_DIR"
    "$UV_BIN" python install 3.12
    PYTHON="$(UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" "$UV_BIN" python find 3.12)"
fi
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)'; then
    echo "Selected interpreter $PYTHON is not a supported Python 3.10–3.12 runtime." >&2
    exit 1
fi

if ! command -v deno >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/deno" ]]; then
    if ! command -v curl >/dev/null 2>&1; then
        echo "Deno is required for full yt-dlp JavaScript support. Install Deno from https://docs.deno.com/runtime/getting_started/installation/" >&2
        exit 1
    fi
    echo "Installing Deno for yt-dlp JavaScript support..."
    export DENO_INSTALL="$HOME/.local"
    curl -fsSL https://deno.land/install.sh | sh
fi

if [[ ! -d "$PROJECT_DIR/venv" ]]; then
    echo "Creating Python environment..."
    "$PYTHON" -m venv "$PROJECT_DIR/venv"
elif ! "$PROJECT_DIR/venv/bin/python" -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)' 2>/dev/null || \
    [[ "$("$PROJECT_DIR/venv/bin/python" -c 'import sys; print(sys.base_prefix)' 2>/dev/null || true)" != "$("$PYTHON" -c 'import sys; print(sys.base_prefix)')" ]]; then
    echo "Replacing the existing project venv to match the selected Python runtime..."
    rm -rf "$PROJECT_DIR/venv"
    "$PYTHON" -m venv "$PROJECT_DIR/venv"
fi
VENV="$PROJECT_DIR/venv"

echo "Installing CPU-compatible PyTorch and application dependencies..."
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip uninstall -y \
    onnxruntime onnxruntime-gpu onnxruntime-openvino onnxruntime-migraphx >/dev/null 2>&1 || true
"$VENV/bin/python" -m pip install \
    "torch==2.4.1+cpu" "torchvision==0.19.1+cpu" \
    --index-url https://download.pytorch.org/whl/cpu
"$VENV/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"

case "$ACCELERATION" in
    cpu) ;;
    nvidia) ORT_PACKAGE="onnxruntime-gpu==1.23.0" ;;
    intel) ORT_PACKAGE="onnxruntime-openvino==1.23.0" ;;
    amd) ORT_PACKAGE="onnxruntime-migraphx==1.23.0" ;;
esac
if [[ "$ACCELERATION" != cpu ]]; then
    echo "Installing ONNX Runtime provider for $ACCELERATION (CPU remains the fallback)..."
    "$VENV/bin/python" -m pip uninstall -y onnxruntime
    "$VENV/bin/python" -m pip install "$ORT_PACKAGE"
fi

MODEL_DIR="$PROJECT_DIR/assets/model_cache/audio-separator"
mkdir -p "$MODEL_DIR"
chmod +x "$PROJECT_DIR/harammute" "$PROJECT_DIR/harammute-open" "$PROJECT_DIR/harammute-server" "$PROJECT_DIR/tray_launcher.py"

USER_BIN="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$USER_BIN" "$APP_DIR" "$AUTOSTART_DIR" "$ICON_DIR"
ln -sfn "$PROJECT_DIR/harammute" "$USER_BIN/harammute"
ln -sfn "$PROJECT_DIR/harammute-open" "$USER_BIN/harammute-open"
ln -sfn "$PROJECT_DIR/tray_launcher.py" "$USER_BIN/harammute-tray"
cp "$PROJECT_DIR/icon.png" "$ICON_DIR/harammute.png"

sed "s|@APP_DIR@|$PROJECT_DIR|g" "$PROJECT_DIR/harammute.desktop" > "$APP_DIR/harammute.desktop"
sed "s|^Exec=.*$|Exec=\"$USER_BIN/harammute-open\" --background|" \
    "$APP_DIR/harammute.desktop" > "$AUTOSTART_DIR/harammute.desktop"

SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"
cp "$PROJECT_DIR/harammute.service" "$SYSTEMD_DIR/harammute.service"

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload || true
fi

echo
echo "Installation complete (requested acceleration: $ACCELERATION). The local model downloads on first use (~66 MB)."
echo "Launch the tray: $PROJECT_DIR/tray_launcher.py"
echo "Enable the background service: systemctl --user enable --now harammute"
echo "Server/API remains on http://127.0.0.1:8765 for extension compatibility."
