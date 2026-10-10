#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="AS-Offical/HaramMute-Linux"
DRY_RUN=0

while (($#)); do
    case "$1" in
        --help|-h)
            echo "Downloads and installs the latest HaramMute release for this Linux distribution."
            echo "Usage: install-release.sh [--dry-run]"
            exit 0
            ;;
        --dry-run) DRY_RUN=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

for dependency in curl sha256sum; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        echo "Missing required command: $dependency" >&2
        exit 1
    fi
done

if [[ "$EUID" -eq 0 && -n "${SUDO_USER:-}" ]]; then
    echo "Run this installer as your normal user; it will request sudo for system packages." >&2
    exit 2
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "Published release packages currently support x86_64 only." >&2
    exit 1
fi
if [[ -e /etc/alpine-release ]] || ldd --version 2>&1 | grep -qi musl; then
    echo "Alpine/musl is not supported by the published HaramMute packages." >&2
    exit 1
fi
if [[ ! -r /etc/os-release ]]; then
    echo "Cannot identify this Linux distribution (/etc/os-release is missing)." >&2
    exit 1
fi
# shellcheck disable=SC1091
. /etc/os-release

case " $ID ${ID_LIKE:-} " in
    *" nixos "*) PACKAGE_KIND="nixos" ;;
    *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*) PACKAGE_KIND="deb" ;;
    *" arch "*|*" manjaro "*|*" cachyos "*|*" endeavouros "*) PACKAGE_KIND="arch" ;;
    *" opensuse-tumbleweed "*) PACKAGE_KIND="opensuse" ;;
    *" fedora "*) PACKAGE_KIND="fedora" ;;
    *) PACKAGE_KIND="appimage" ;;
esac

if [[ "$PACKAGE_KIND" == "nixos" ]]; then
    for dependency in nix-store nix-env tar zstd; do
        if ! command -v "$dependency" >/dev/null 2>&1; then
            echo "NixOS installation requires $dependency." >&2
            exit 1
        fi
    done
elif ! command -v python3 >/dev/null 2>&1; then
    echo "Missing required command: python3" >&2
    exit 1
fi

TEMP_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

if [[ "$PACKAGE_KIND" == "nixos" ]]; then
    RELEASE_TAG="latest"
    ASSET_NAME="harammute-nixos-x86_64-nixstore.tar.zst"
    ASSET_URL="https://github.com/$REPOSITORY/releases/latest/download/$ASSET_NAME"
    CHECKSUM_URL="https://github.com/$REPOSITORY/releases/latest/download/SHA256SUMS"
else
    RELEASE_JSON="$TEMP_DIR/release.json"
    curl --fail --silent --show-error --location --retry 3 \
        "https://api.github.com/repos/$REPOSITORY/releases/latest" \
        --output "$RELEASE_JSON"

    IFS=$'\t' read -r RELEASE_TAG ASSET_NAME ASSET_URL < <(
        PACKAGE_KIND="$PACKAGE_KIND" VERSION_ID="${VERSION_ID:-}" \
            python3 - "$RELEASE_JSON" <<'PY'
import json
import os
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    release = json.load(stream)
assets = {asset["name"]: asset["browser_download_url"] for asset in release.get("assets", [])}
kind = os.environ["PACKAGE_KIND"]
version = os.environ.get("VERSION_ID", "")

if kind == "deb":
    candidates = [name for name in assets if name.endswith("_amd64.deb")]
elif kind == "arch":
    candidates = [name for name in assets if name.endswith("x86_64.pkg.tar.zst")]
elif kind == "opensuse":
    candidates = [name for name in assets if name.endswith("x86_64.rpm") and ".fc" not in name]
elif kind == "fedora":
    candidates = [name for name in assets if f".fc{version}." in name and name.endswith("x86_64.rpm")]
else:
    candidates = []

if not candidates and kind != "nixos":
    kind = "appimage"
    candidates = [name for name in assets if name.endswith("x86_64.AppImage")]
if len(candidates) != 1:
    raise SystemExit(f"Latest release has no unambiguous {kind} package for this system.")

name = candidates[0]
print(release["tag_name"], name, assets[name], sep="\t")
PY
    )
    CHECKSUM_URL="https://github.com/$REPOSITORY/releases/download/$RELEASE_TAG/SHA256SUMS"
fi

if [[ -z "${RELEASE_TAG:-}" || -z "${ASSET_NAME:-}" || -z "${ASSET_URL:-}" ]]; then
    echo "Could not select a compatible package from the latest release." >&2
    exit 1
fi

echo "Latest release: $RELEASE_TAG"
echo "Distribution: ${PRETTY_NAME:-$ID} (${PACKAGE_KIND})"
echo "Package: $ASSET_NAME"
if ((DRY_RUN)); then
    echo "Dry run: no package was downloaded or installed."
    exit 0
fi

curl --fail --silent --show-error --location --retry 3 \
    "$ASSET_URL" --output "$TEMP_DIR/$ASSET_NAME"
curl --fail --silent --show-error --location --retry 3 \
    "$CHECKSUM_URL" --output "$TEMP_DIR/SHA256SUMS"

if ! EXPECTED_SHA="$(awk -v asset="$ASSET_NAME" '$2 == asset { print $1; found = 1 } END { if (!found) exit 1 }' "$TEMP_DIR/SHA256SUMS")"; then
    echo "No checksum entry found for $ASSET_NAME in the latest release." >&2
    exit 1
fi
ACTUAL_SHA="$(sha256sum "$TEMP_DIR/$ASSET_NAME" | awk '{print $1}')"
if [[ "$EXPECTED_SHA" != "$ACTUAL_SHA" ]]; then
    echo "Checksum verification failed for $ASSET_NAME." >&2
    exit 1
fi
echo "SHA256 checksum verified."

run_privileged() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    else
        if ! command -v sudo >/dev/null 2>&1; then
            echo "sudo is required to install the selected system package." >&2
            exit 1
        fi
        sudo "$@"
    fi
}

case "$ASSET_NAME" in
    *.deb)
        command -v apt-get >/dev/null 2>&1 || { echo "apt-get is required for this Debian package." >&2; exit 1; }
        run_privileged apt-get update
        run_privileged apt-get install -y "$TEMP_DIR/$ASSET_NAME"
        ;;
    *.rpm)
        if [[ "$PACKAGE_KIND" == "opensuse" ]]; then
            command -v zypper >/dev/null 2>&1 || { echo "zypper is required for this RPM package." >&2; exit 1; }
            echo "Note: the openSUSE RPM is unsigned; SHA256 was checked against the release checksum file."
            run_privileged zypper --no-gpg-checks --non-interactive install "$TEMP_DIR/$ASSET_NAME"
        else
            command -v dnf >/dev/null 2>&1 || { echo "dnf is required for this Fedora package." >&2; exit 1; }
            run_privileged dnf install -y "$TEMP_DIR/$ASSET_NAME"
        fi
        ;;
    *.pkg.tar.zst)
        command -v pacman >/dev/null 2>&1 || { echo "pacman is required for this Arch package." >&2; exit 1; }
        run_privileged pacman -U --noconfirm "$TEMP_DIR/$ASSET_NAME"
        ;;
    *nixstore.tar.zst)
        NIXOS_DIR="$TEMP_DIR/nixos-package"
        mkdir -p "$NIXOS_DIR"
        tar --zstd -xf "$TEMP_DIR/$ASSET_NAME" -C "$NIXOS_DIR"
        STORE_PATH="$(<"$NIXOS_DIR/harammute-store-path")"
        if [[ ! "$STORE_PATH" =~ ^/nix/store/[a-z0-9]{32}-harammute-[^/]+$ ]]; then
            echo "The release archive contains an invalid HaramMute store path." >&2
            exit 1
        fi
        zstd -dc "$NIXOS_DIR/harammute.store.zst" | nix-store --import
        nix-env --install "$STORE_PATH"
        ;;
    *.AppImage)
        APP_DIR="${HOME:?HOME must be set}/.local/opt/harammute"
        BIN_DIR="${HOME}/.local/bin"
        APP_PATH="$APP_DIR/HaramMute.AppImage"
        LAUNCHER="$BIN_DIR/harammute-appimage-open"
        DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
        mkdir -p "$APP_DIR" "$BIN_DIR" "$DESKTOP_DIR"
        install -m 0755 "$TEMP_DIR/$ASSET_NAME" "$APP_PATH.new"
        mv -f "$APP_PATH.new" "$APP_PATH"
        printf '#!/usr/bin/env bash\nset -euo pipefail\nexport APPIMAGE_EXTRACT_AND_RUN=1\nexec %q --open "$@"\n' "$APP_PATH" > "$LAUNCHER"
        chmod 0755 "$LAUNCHER"
        ESCAPED_LAUNCHER="${LAUNCHER//\\/\\\\}"
        ESCAPED_LAUNCHER="${ESCAPED_LAUNCHER//\"/\\\"}"
        ESCAPED_LAUNCHER="${ESCAPED_LAUNCHER//%/%%}"
        cat > "$DESKTOP_DIR/harammute-appimage.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=HaramMute
Comment=Local vocal separation for the HaramMute browser extension
Exec="$ESCAPED_LAUNCHER"
Icon=multimedia-player
Terminal=false
Categories=AudioVideo;Audio;
StartupNotify=false
EOF
        echo "Installed the AppImage for this glibc-based distribution. Launch HaramMute from the applications menu or run $LAUNCHER."
        ;;
    *)
        echo "Unsupported release asset: $ASSET_NAME" >&2
        exit 1
        ;;
esac

echo "HaramMute $RELEASE_TAG installed. Install the required browser extension separately."
