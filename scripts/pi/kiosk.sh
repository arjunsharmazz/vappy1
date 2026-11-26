#!/usr/bin/env bash
# Opens the frame full-screen in Chromium once the backend answers (started by the desktop autostart).
URL="http://localhost:8000/"
for _ in $(seq 1 90); do
  curl -sf -o /dev/null "http://127.0.0.1:8000/health" && break
  sleep 2
done
BROWSER="$(command -v chromium-browser || command -v chromium)"
# localhost counts as a secure page, so the microphone works; the flags allow sound without a
# tap and accept the microphone/camera prompt automatically (it is your own frame).
exec "$BROWSER" --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream \
  --check-for-update-interval=31536000 --disable-features=Translate \
  --password-store=basic "$URL"
