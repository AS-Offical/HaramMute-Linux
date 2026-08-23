#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

echo "=== HaramMute Linux Setup Script ==="
echo

# 1. Create venv if missing
if [ ! -d "$PROJECT_DIR/venv" ]; then
    echo "Creating Python venv..."
    python3 -m venv "$PROJECT_DIR/venv"
else
    echo "venv already exists."
fi

VENV="$PROJECT_DIR/venv"

# 2. Install torch (CPU) + rest of deps
echo "Installing torch (CPU build)..."
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install "torch==2.4.1+cpu" "torchvision==0.19.1+cpu" --index-url https://download.pytorch.org/whl/cpu

echo "Installing remaining dependencies..."
"$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt"

# 3. Ensure model directory exists & download model if missing
echo "Setting up model cache..."
MODEL_DIR="$PROJECT_DIR/assets/model_cache/audio-separator"
mkdir -p "$MODEL_DIR"

# audio-separator's Separator will auto-download UVR-MDX-NET-Voc_FT.onnx
# into model_dir on first separation if not present (uses HF repo).
# If you have a local ONNX, place it here; otherwise first run will download ~66MB.
echo "Model directory ready. First separation will auto-download the model if missing."

# 4. Ensure scripts are executable
chmod +x "$PROJECT_DIR/harammute"
chmod +x "$PROJECT_DIR/tray_launcher.py"

# 5. Generate autostart .desktop if not present
AUTOSTART="$HOME/.config/autostart/harammute-tray.desktop"
if [ ! -f "$AUTOSTART" ]; then
    echo "Creating autostart entry for tray icon..."
    mkdir -p "$HOME/.config/autostart"
    sed "s|/home/kyler|$HOME|g" "$PROJECT_DIR/harammute.desktop" > "$AUTOSTART"
    chmod +x "$AUTOSTART"
    echo "Autostart entry created at $AUTOSTART"
else
    echo "Autostart entry already exists."
fi

echo
echo "=== Setup Complete ==="
echo "Run with: $PROJECT_DIR/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765"
echo "Or simply: $PROJECT_DIR/harammute"
echo "Tray launcher: $PROJECT_DIR/tray_launcher.py"
echo "See README.md for details."