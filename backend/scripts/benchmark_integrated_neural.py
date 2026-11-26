"""Smoke benchmark of the extracted LivePortrait modules and MuseTalk blending."""
import json
from pathlib import Path
import sys
import tempfile
import time
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    import psutil
    import cv2
    from app.services.neural_avatar.model_loader import LivePortraitCPU
    from app.services.neural_avatar.base_engine import MotionControl
    engine = LivePortraitCPU(); process = psutil.Process()
    result = {'frames': [], 'mode': 'CPU, 128px, real inference'}
    peak = [0]; done = threading.Event()
    def sample():
        while not done.wait(.05): peak[0] = max(peak[0], process.memory_info().rss)
    monitor = threading.Thread(target=sample, daemon=True); monitor.start()
    try:
        # Existing validated avatar avoids importing FastAPI into the isolated neural runtime.
        avatar = next(p for p in (ROOT / 'avatar_data').glob('*/avatar.json')
                      if json.loads(p.read_text()).get('animation_available'))
        details = json.loads(avatar.read_text())
        encoded = (avatar.parent / 'original.jpg').read_bytes()
        result['model'] = engine.load()
        with tempfile.TemporaryDirectory(prefix='living-neural-') as tmp:
            source = Path(tmp) / 'source.jpg'; source.write_bytes(encoded)
            state = engine.prepare_avatar(source, details, Path(tmp) / 'cache', 128)
            for name, control in [('neutral', MotionControl()), ('smile', MotionControl(smile=.5)),
                                  ('speech', MotionControl(mouth_open=.5, mouth_only=True))]:
                start = time.perf_counter(); frame = engine.render(state, control)
                elapsed = time.perf_counter() - start
                result['frames'].append({'name': name, 'seconds': elapsed})
                cv2.imwrite(str(ROOT / '.tools' / ('integrated-neural-' + name + '.png')), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                print(name, round(elapsed, 3), 'seconds', flush=True)
        result['status'] = 'passed'
    except Exception as error:
        result['status'] = 'failed'; result['error'] = str(error); raise
    finally:
        done.set(); monitor.join(1)
        result['peak_rss_bytes'] = peak[0]
        (ROOT / 'neural_integration_benchmark.json').write_text(json.dumps(result, indent=2))
        engine.unload()


if __name__ == '__main__': main()
