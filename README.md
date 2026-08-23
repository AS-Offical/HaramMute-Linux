# HaramMute — Linux Build

Local vocal-separation server for the HaramMute browser extension.
Pure-Python rebuild of the Windows desktop app (whose `pipeline`,
`local_processing`, and `jobs` modules shipped only as compiled
Windows binaries). API-compatible with the original FastAPI service.

## Architecture

```
Browser extension ──HTTP──> uvicorn (127.0.0.1:8765)
                              └─ app/main.py        (API, unchanged from upstream)
                                 app/jobs.py        (JSON-persisted job store)  [rebuilt]
                                 app/local_processing.py                       [rebuilt]
                                    yt-dlp download (cookie fallback chain)
                                    ffmpeg: WAV convert / chunk split / MP3 loudnorm
                                    audio-separator UVR-MDX-NET-Voc_FT.onnx (CPU/CUDA)
                                 app/pipeline.py    (orchestration + progress)  [rebuilt]
```

Data lives in `~/.local/share/HaramMute/` (`jobs/`, `models/`, logs via journald).

## Requirements

- Linux, Python 3.10–3.12, ffmpeg + ffprobe on PATH
- CPU works everywhere; NVIDIA CUDA used automatically if onnxruntime-gpu is installed
- ~1.5 GB disk for the venv

## Install

```bash
cd ~/harammute-linux
python3 -m venv venv
venv/bin/pip install torch==2.4.1 torchvision==0.19.1 \
    --index-url https://download.pytorch.org/whl/cpu   # CPU build; small & old-CPU safe
venv/bin/pip install -r requirements.txt
```

On AVX2-capable CPUs you may swap in newer torch/onnxruntime builds.

## Run

Console server:
```bash
./harammute                 # http://127.0.0.1:8765
./harammute --port 8901     # custom port
```

As a user service (survives logout):
```bash
cp harammute.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now harammute
journalctl --user -u harammute -f      # logs
```

Tray icon: `python3 tray_launcher.py` (system python3; needs the installed
`gir1.2-ayatanaappindicator3-0.1`). Uses AppIndicator/SNI, so it appears in
modern XFCE/GNOME panels. It reuses an already-running server instead of
spawning a duplicate. For autostart at login, copy `harammute-tray.desktop`
to `~/.config/autostart/`.

Desktop entry: copy `harammute.desktop` to `~/.local/share/applications/`.

The browser extension should point at `http://127.0.0.1:8765` (same API as the
Windows app). Jobs are authenticated-bypassed in local mode by design.

## Config (environment)

| Variable | Default | Meaning |
|---|---|---|
| `HARAMMUTE_DATA_DIR` | `~/.local/share/HaramMute` | data root |
| `MUSIC_REMOVER_CHUNK_THRESHOLD` | `120` | seconds; longer audio splits into 60s chunks |
| `MUSIC_REMOVER_FORCE_CPU` | unset | set `true` to disable CUDA |
| `MUSIC_REMOVER_MODEL_NAME` | `UVR-MDX-NET-Voc_FT.onnx` | separator model |
| `MUSIC_REMOVER_ENCODING_QUALITY` | `4` | MP3 VBR quality (0 best … 9 fastest) |
| `HARAMMUTE_TELEMETRY_ENABLED` | off | opt-in PostHog telemetry |

## Verified

End-to-end on IvyBridge (3-core, no dGPU): a 19 s YouTube video →
vocals-only MP3 in ~135 s (download 9 s, separation 113 s on CPU).
Output validated with ffprobe (19.1 s, VBR stereo).

## Notes

- `app/main.py`, `schemas.py`, `limits.py`, `config.py` are the unmodified
  upstream sources from the Windows install.
- Telemetry ships disabled; the PostHog key remains only inside the optional module.
- The bundled ONNX model lives in `assets/model_cache/audio-separator/` and is
  seeded into the data dir on first run (no downloads).
# HaramMute-Linux
