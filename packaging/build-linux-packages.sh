#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-$ROOT/dist}"
APPIMAGETOOL="${APPIMAGETOOL:-}"
LINUXDEPLOY="${LINUXDEPLOY:-}"

if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "This initial package builder targets x86_64; other architectures need matching Python and ONNX wheels." >&2
    exit 2
fi
if [[ ! -x "$ROOT/venv/bin/python" ]]; then
    echo "Install the runtime first with ./install.sh --managed-python --acceleration cpu" >&2
    exit 1
fi
mkdir -p "$OUTPUT_DIR"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
APP_VERSION="$(sed -n 's/.*HARAMMUTE_VERSION:-\([0-9.]*\)-linux.*/\1/p' "$ROOT/harammute")"
APP_VERSION="${APP_VERSION:-1.0.18}"
BUILT_PACKAGES=0
PYTHON_MINOR="$("$ROOT/venv/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_BASE="$("$ROOT/venv/bin/python" -c 'import sys; print(sys.base_prefix)')"
if [[ ! -x "$PYTHON_BASE/bin/python${PYTHON_MINOR}" ]]; then
    echo "The selected runtime is not a standalone managed Python. Reinstall with ./install.sh --managed-python." >&2
    exit 1
fi
SITE_PACKAGES="$ROOT/venv/lib/python${PYTHON_MINOR}/site-packages"
if [[ ! -d "$SITE_PACKAGES" ]]; then
    echo "Python dependencies were not found in $SITE_PACKAGES." >&2
    exit 1
fi

copy_runtime_tree() {
    local destination="$1"
    mkdir -p "$destination"
    tar -C "$ROOT" \
        --exclude=.git --exclude=dist --exclude=server_data --exclude=venv \
        --exclude='__pycache__' --exclude='*.pyc' \
        -cf - . | tar -C "$destination" -xf -
}

copy_python_runtime() {
    local destination="$1"
    mkdir -p "$destination/python-runtime" "$destination/python-packages"
    cp -a "$PYTHON_BASE/." "$destination/python-runtime/"
    cp -a "$SITE_PACKAGES/." "$destination/python-packages/"
}

if command -v dpkg-deb >/dev/null 2>&1; then
    # Native Debian package; jobs and models remain per-user.
    DEB_ROOT="$WORK_DIR/deb"
    mkdir -p "$DEB_ROOT/DEBIAN" "$DEB_ROOT/opt/harammute-linux"
    copy_runtime_tree "$DEB_ROOT/opt/harammute-linux"
    copy_python_runtime "$DEB_ROOT/opt/harammute-linux"
    if [[ -x "$HOME/.local/bin/deno" ]]; then
        install -D -m 0755 "$HOME/.local/bin/deno" "$DEB_ROOT/opt/harammute-linux/bin/deno"
    elif command -v deno >/dev/null 2>&1; then
        install -D -m 0755 "$(command -v deno)" "$DEB_ROOT/opt/harammute-linux/bin/deno"
    else
        echo "Run ./install.sh first so Deno is installed for yt-dlp media support." >&2
        exit 1
    fi
    sed "s/^Version:.*/Version: $APP_VERSION-3/" \
        "$ROOT/packaging/deb/control" > "$DEB_ROOT/DEBIAN/control"
    cp "$ROOT/packaging/deb/postinst" "$DEB_ROOT/DEBIAN/postinst"
    cp "$ROOT/packaging/deb/prerm" "$DEB_ROOT/DEBIAN/prerm"
    chmod 0755 "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/prerm"
    dpkg-deb --root-owner-group --build "$DEB_ROOT" "$OUTPUT_DIR/harammute-linux_${APP_VERSION}-3_amd64.deb"
    BUILT_PACKAGES=1
else
    echo "dpkg-deb is unavailable; skipping the Debian package."
fi

if [[ -n "$APPIMAGETOOL" && -x "$APPIMAGETOOL" && -n "$LINUXDEPLOY" && -x "$LINUXDEPLOY" ]]; then
    if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
        # AppImage uses the selected Python runtime and checks the host's
        # GTK/AppIndicator bindings before starting the tray and local server.
        APPDIR="$WORK_DIR/HaramMute.AppDir"
        APP_ROOT="$APPDIR/usr/lib/harammute-linux"
        copy_runtime_tree "$APP_ROOT"
        copy_python_runtime "$APP_ROOT"
        install -D -m 0755 "$(command -v ffmpeg)" "$APP_ROOT/bin/ffmpeg"
        install -D -m 0755 "$(command -v ffprobe)" "$APP_ROOT/bin/ffprobe"
        install -D -m 0644 "$ROOT/packaging/appimage/harammute.desktop" "$APPDIR/harammute.desktop"
        install -D -m 0644 "$ROOT/icon.png" "$APPDIR/harammute.png"
        if [[ -x "$HOME/.local/bin/deno" ]]; then
            install -D -m 0755 "$HOME/.local/bin/deno" "$APP_ROOT/bin/deno"
        elif [[ -x "$HOME/.deno/bin/deno" ]]; then
            install -D -m 0755 "$HOME/.deno/bin/deno" "$APP_ROOT/bin/deno"
        elif command -v deno >/dev/null 2>&1; then
            install -D -m 0755 "$(command -v deno)" "$APP_ROOT/bin/deno"
        fi
        if [[ ! -x "$APP_ROOT/bin/deno" ]]; then
            echo "Run ./install.sh first so Deno is available for yt-dlp media support." >&2
            exit 1
        fi
        # Build on the oldest supported glibc baseline; GPU drivers remain host-provided.
        LD_LIBRARY_PATH="$APP_ROOT/python-packages/torch/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
        "$LINUXDEPLOY" --appdir "$APPDIR" \
            --executable "$APP_ROOT/bin/ffmpeg" \
            --executable "$APP_ROOT/bin/ffprobe"
        install -D -m 0755 "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
        ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" \
            "$APPDIR" "$OUTPUT_DIR/HaramMute-${APP_VERSION}-x86_64.AppImage"
        chmod 0755 "$OUTPUT_DIR/HaramMute-${APP_VERSION}-x86_64.AppImage"
        BUILT_PACKAGES=1
    else
        echo "Skipping AppImage: the build host lacks ffmpeg or ffprobe."
    fi
else
    echo "Skipping AppImage: set APPIMAGETOOL and LINUXDEPLOY to build it."
fi

if ((BUILT_PACKAGES == 0)); then
    echo "No package was built. Install dpkg-deb or provide the AppImage build tools." >&2
    exit 1
fi

echo "Built Linux packages in: $OUTPUT_DIR"
