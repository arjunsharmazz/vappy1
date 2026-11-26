#!/usr/bin/env bash
# Run the frame by hand (without the systemd service): backend in this terminal, page in Chromium.
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/backend"
"$ROOT/scripts/pi/kiosk.sh" &
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
