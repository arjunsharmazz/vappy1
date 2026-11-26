#!/usr/bin/env bash
# Update the frame on the Pi after you pushed changes from the laptop:
#   bash scripts/pi/update.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
git pull
backend/.venv/bin/python -m pip install -q -r backend/requirements-pi.txt
backend/.venv/bin/python backend/scripts/download_models.py --pi
(cd frontend && npm ci --no-audit --no-fund --silent && npm run build)
sudo systemctl restart avatar-frame
echo "Updated. New avatars from avtars/prepared appear after the page reloads (F5)."
