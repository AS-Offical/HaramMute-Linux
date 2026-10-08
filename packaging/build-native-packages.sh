#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${1:-$ROOT/dist}"
VERSION="$(sed -n 's/.*HARAMMUTE_VERSION:-\([0-9.]*\)-linux.*/\1/p' "$ROOT/harammute")"
VERSION="${VERSION:-1.0.18}"
RUNTIME_PYTHON="$ROOT/venv/bin/python"

if [[ ! -x "$RUNTIME_PYTHON" ]]; then
    echo "Prepare a Python 3.12 runtime first: ./install.sh --managed-python --acceleration cpu" >&2
    exit 1
fi
PYTHON_MINOR="$("$RUNTIME_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYTHON_BASE="$("$RUNTIME_PYTHON" -c 'import sys; print(sys.base_prefix)')"
if [[ "$PYTHON_MINOR" != 3.12 || ! -x "$PYTHON_BASE/bin/python3.12" ]]; then
    echo "Native packages require the managed standalone Python 3.12 runtime." >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
RUNTIME_DIR="$WORK_DIR/harammute-linux"
mkdir -p "$RUNTIME_DIR/python-runtime" "$RUNTIME_DIR/python-packages"
tar -C "$ROOT" \
    --exclude=.git --exclude=dist --exclude=server_data --exclude=venv \
    --exclude='__pycache__' --exclude='*.pyc' \
    -cf - . | tar -C "$RUNTIME_DIR" -xf -
cp -a "$PYTHON_BASE/." "$RUNTIME_DIR/python-runtime/"
cp -a "$ROOT/venv/lib/python3.12/site-packages/." "$RUNTIME_DIR/python-packages/"
rm -rf "$RUNTIME_DIR/python-runtime/include" "$RUNTIME_DIR/python-runtime/share/doc"
find "$RUNTIME_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
if [[ -x "$HOME/.local/bin/deno" ]]; then
    install -D -m 0755 "$HOME/.local/bin/deno" "$RUNTIME_DIR/bin/deno"
elif command -v deno >/dev/null 2>&1; then
    install -D -m 0755 "$(command -v deno)" "$RUNTIME_DIR/bin/deno"
else
    echo "Run ./install.sh first so Deno is installed for yt-dlp media support." >&2
    exit 1
fi

if command -v makepkg >/dev/null 2>&1; then
    ARCH_DIR="$WORK_DIR/arch"
    mkdir -p "$ARCH_DIR"
    ln -s "$RUNTIME_DIR" "$ARCH_DIR/harammute-linux"
    sed "s/^pkgver=.*/pkgver=$VERSION/" "$ROOT/packaging/arch/PKGBUILD" > "$ARCH_DIR/PKGBUILD"
    cp "$ROOT/packaging/arch/harammute" "$ARCH_DIR/harammute"
    cp "$ROOT/harammute-open" "$ARCH_DIR/harammute-open"
    cp "$ROOT/packaging/arch/harammute-tray" "$ARCH_DIR/harammute-tray"
    cp "$ROOT/packaging/arch/harammute.desktop" "$ARCH_DIR/harammute.desktop"
    cp "$ROOT/packaging/arch/harammute.service" "$ARCH_DIR/harammute.service"
    (cd "$ARCH_DIR" && makepkg --force)
    find "$ARCH_DIR" -maxdepth 1 -name '*.pkg.tar.*' -exec cp -t "$OUTPUT_DIR" {} +
fi

if command -v rpmbuild >/dev/null 2>&1; then
    RPM_TOP="$WORK_DIR/rpm"
    mkdir -p "$RPM_TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
    tar -czf "$RPM_TOP/SOURCES/harammute-linux.tar.gz" -C "$WORK_DIR" harammute-linux
    cp "$ROOT/packaging/arch/harammute" "$RPM_TOP/SOURCES/harammute"
    cp "$ROOT/harammute-open" "$RPM_TOP/SOURCES/harammute-open"
    cp "$ROOT/packaging/arch/harammute-tray" "$RPM_TOP/SOURCES/harammute-tray"
    cp "$ROOT/packaging/arch/harammute.desktop" "$RPM_TOP/SOURCES/harammute.desktop"
    cp "$ROOT/packaging/arch/harammute.service" "$RPM_TOP/SOURCES/harammute.service"
    sed "s/^Version:        .*/Version:        $VERSION/" \
        "$ROOT/packaging/rpm/harammute-linux.spec" > "$RPM_TOP/SPECS/harammute-linux.spec"
    rpmbuild --define "_topdir $RPM_TOP" -bb "$RPM_TOP/SPECS/harammute-linux.spec"
    find "$RPM_TOP/RPMS" -type f -name '*.rpm' -exec cp -t "$OUTPUT_DIR" {} +
fi

if ! command -v makepkg >/dev/null 2>&1 && ! command -v rpmbuild >/dev/null 2>&1; then
    echo "Install makepkg (Arch) or rpmbuild (Fedora/openSUSE) to build a native package." >&2
    exit 1
fi

echo "Native packages built in: $OUTPUT_DIR"
