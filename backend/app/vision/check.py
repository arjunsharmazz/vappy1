"""Manual camera test: `python -m app.vision.check` (from backend/). Prints presence and face position."""
import time

from ..logging_setup import setup_logging
from .service import service


def main(seconds=20):
    setup_logging("INFO")
    service.subscribe()
    print("Move left/right in front of the camera. Ctrl+C to stop.")
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            s, _ = service.snapshot()
            bar = [" "] * 21
            if s.get("present"):
                bar[max(0, min(20, int((s["x"] + 1) * 10)))] = "O"
            print(f"camera={s.get('camera')!s:5} present={s.get('present')!s:5} x={s.get('x', 0):+.2f} "
                  f"y={s.get('y', 0):+.2f} size={s.get('size', 0):.2f} fps={s.get('fps', 0):4.1f} [{''.join(bar)}]", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        service.unsubscribe()
        service.idle_stop_seconds = 0


if __name__ == "__main__":
    main()
