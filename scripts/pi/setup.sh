#!/usr/bin/env bash
# One-time setup of the AI Avatar Frame on a Raspberry Pi 5 (4 GB).
# Raspberry Pi OS 64-bit with desktop: Bookworm recommended (Python 3.11, everything works);
# Trixie works too (Python 3.11 is installed next to the system Python with uv).
#
#   cd ~/new-project-start && bash scripts/pi/setup.sh
#
# Safe to run again (it skips what is already done).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

say "Checking the device"
ARCH="$(uname -m)"
MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo unknown)"
echo "Model: $MODEL | arch: $ARCH | RAM: $(free -h | awk '/Mem:/{print $2}')"
[ "$ARCH" = "aarch64" ] || warn "This expects 64-bit Raspberry Pi OS (aarch64). Found: $ARCH"

say "Installing system packages (needs sudo)"
CHROMIUM=chromium-browser
apt-cache show chromium-browser >/dev/null 2>&1 || CHROMIUM=chromium
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev ffmpeg curl nodejs npm "$CHROMIUM" rpicam-apps alsa-utils || \
  sudo apt-get install -y python3-venv python3-dev ffmpeg curl nodejs npm "$CHROMIUM" alsa-utils

say "Python environment (Python 3.11, same as the laptop)"
PYV="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
if [ ! -x backend/.venv/bin/python ]; then
  if [ "$PYV" = "3.11" ] || [ "$PYV" = "3.12" ]; then
    python3 -m venv backend/.venv
  else
    # Trixie ships Python 3.13, for which MediaPipe has no wheels: use a private Python 3.11.
    command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    uv venv --python 3.11 backend/.venv
    backend/.venv/bin/python -m ensurepip --upgrade || true
  fi
fi
PY=backend/.venv/bin/python
$PY -m pip install --upgrade pip wheel
$PY -m pip install -r backend/requirements-pi.txt
# Camera feelings and hand gestures. --no-deps: MediaPipe would pull a second OpenCV build that
# conflicts with opencv-python-headless. Optional: the frame works without it.
if ! $PY -m pip install --no-deps mediapipe==1.2.3 absl-py==2.5.1 || ! $PY -m pip install matplotlib; then
  warn "MediaPipe could not be installed: camera feelings/gestures stay off (everything else works)."
fi

say "Downloading models (~350 MB, once)"
$PY backend/scripts/download_models.py --pi || warn "Some models failed; run this script again later."

say "Building the web page"
NODE_MAJOR="$(node -v 2>/dev/null | sed 's/v\([0-9]*\).*/\1/' || echo 0)"
if [ "${NODE_MAJOR:-0}" -lt 18 ]; then
  warn "Node.js 18+ is needed to build the page (found $(node -v 2>/dev/null || echo none))."
else
  (cd frontend && npm ci --no-audit --no-fund && npm run build)
fi

say "API key"
if [ ! -f config/.env ]; then
  cp config/.env.example config/.env
  warn "Put your Gemini key in config/.env (GEMINI_API_KEY=...) — without it the frame runs offline only."
fi

say "Starting the backend automatically at boot (systemd)"
sed -e "s|__USER__|$USER|g" -e "s|__ROOT__|$ROOT|g" scripts/pi/avatar-frame.service | \
  sudo tee /etc/systemd/system/avatar-frame.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now avatar-frame.service

say "Opening the frame full-screen when the desktop starts (kiosk)"
chmod +x scripts/pi/kiosk.sh scripts/pi/start.sh
LINE="$ROOT/scripts/pi/kiosk.sh &"
mkdir -p "$HOME/.config/labwc"
grep -qsF "$LINE" "$HOME/.config/labwc/autostart" || echo "$LINE" >> "$HOME/.config/labwc/autostart"
if [ -f "$HOME/.config/wayfire.ini" ] && ! grep -qF "avatar_frame" "$HOME/.config/wayfire.ini"; then
  grep -q '^\[autostart\]' "$HOME/.config/wayfire.ini" || printf '\n[autostart]\n' >> "$HOME/.config/wayfire.ini"
  sed -i "/^\[autostart\]/a avatar_frame = $ROOT/scripts/pi/kiosk.sh" "$HOME/.config/wayfire.ini"
fi
# The user must be allowed to use the camera.
sudo usermod -aG video "$USER" || true

say "Done"
cat <<EOF
- Backend:  sudo systemctl status avatar-frame   (logs: journalctl -u avatar-frame -f)
- Open now: $ROOT/scripts/pi/kiosk.sh   (or reboot: it opens full-screen by itself)
- Sound: the Pi 5 has no headphone jack — use HDMI speakers or a USB speaker; a USB microphone.
- Temperature: vcgencmd measure_temp   (keep it under ~75 °C: Active Cooler or the official case fan)
EOF
