# Contributing to HaramMute Linux

First of all, thank you for considering contributing! This project is a voluntary port of the HaramMute application to Linux, and contributions are welcome.

## 📋 Table of Contents
1. [Code of Conduct](#code-of-conduct)
2. [Reporting Issues](#reporting-issues)
3. [Feature Requests](#feature-requests)
4. [Development Setup](#development-setup)
5. [Pull Request Process](#pull-request-process)
6. [License](#license)

---

## 🛠️ Code of Conduct

Be respectful and inclusive. This is a community-driven project, and everyone is expected to communicate politely.

---

## 🐛 Reporting Issues

If you find a bug or unexpected behavior:

- **Search first** – check if the issue already exists in the [GitHub Issues](https://github.com/AbdullahSalemOffical/HaramMute-Linux/issues) tab.
- **Provide a clear title** – e.g., "CPU SIGILL on IvyBridge during vocal separation".
- **Steps to reproduce** – describe the exact actions that trigger the issue.
- **Environment details** –
  - OS / Distro (e.g., XFCE on Ubuntu 22.04)
  - CPU model (e.g., Intel IvyBridge)
  - Python version (`python3 --version`)
  - Output of `ffmpeg -version` and `python3 -c "import torch; print(torch.__version)"`
- **Logs** – attach relevant log excerpts (journalctl for systemd, or terminal output).

---

## ✨ Feature Requests

 Ideas welcome! Use the [GitHub Discussions](https://github.com/AbdullahSalemOffical/HaramMute-Linux/discussions) (or open an issue with the label `enhancement`) to:
- Suggest new features (e.g., GUI, Docker support, batch processing).
- Vote on existing proposals.
- Describe the use case / why the feature matters.

---

## 🛠️ Development Setup

If you want to work on the code locally:

### Prerequisites
- Linux (tested on XFCE / Ubuntu-based, IvyBridge CPU, 3 cores, 6.7 GB RAM).
- `ffmpeg` and `ffprobe` on `PATH`.
- Python 3.10–3.12.

### 1. Fork & clone
```bash
git fork https://github.com/AbdullahSalemOffical/HaramMute-Linux.git
git clone https://github.com/YourUsername/HaramMute-Linux.git
cd HaramMute-Linux
```

### 2. Create a virtual environment
```bash
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install --upgrade pip
pip install "torch==2.4.1+cpu" "torchvision==0.19.1+cpu" --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

### 4. Run the server locally
```bash
./harammute               # console mode
# or
python3 tray_launcher.py  # system‑tray mode (needs X11 / DISPLAY)
```

### 5. Test the pipeline
- Submit a short YouTube video (e.g., `jNQXAC9IVRw` “Me at the zoo”).
- Verify that `GET /jobs/{id}/stems/vocals` returns a valid MP3.
- Check that `processing_stats` contains reasonable timings.

---

## 🌿 Pull Request Process

1. **Branch from `main`** – create a new branch for your change:
   ```bash
   git checkout -b feature/short-description
   # or
   git checkout -b bugfix/issue-number
   ```

2. **Make your changes** – follow the existing code style (PEP 8 for Python, minimal comments, sensible variable names).

3. **Test your changes** – run the existing test scenarios (download + separation of a short clip) and ensure no regressions.

4. **Commit with a clear message**
   ```bash
   git commit -m "fix: resolve SIGILL on old‑CPU separation (onnxruntime 1.23)"
   ```

5. **Push to your fork**
   ```bash
   git push origin feature/short-description
   ```

6. **Open a Pull Request** on GitHub:
   - Fill the PR template (if one exists).
   - Reference any related issues: `Fixes #123`.
   - Describe what you changed and why.
   - Attach screenshots or log excerpts if helpful.

7. **Respond to review** – maintainers may ask for adjustments. Once approved, the PR will be merged.

---

## 📜 License

By contributing, you agree that your contributions will be released under the [MIT License](LICENSE) that covers the project.

Thank you for helping make HaramMute Linux better! 🎉