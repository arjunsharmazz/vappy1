"""Inspect native-resolution neural frames on a specified existing portrait."""
import json
from pathlib import Path
import sys
import time
import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.neural_avatar.model_loader import LivePortraitCPU
from app.services.neural_avatar.base_engine import MotionControl

folder = ROOT / 'avatar_data' / sys.argv[1]
metadata = json.loads((folder / 'avatar.json').read_text())
engine = LivePortraitCPU()
try:
    engine.load()
    prepared = engine.prepare_avatar(folder / 'original.jpg', metadata, folder / 'neural', 256)
    for name, control in [('neutral', MotionControl()), ('blink', MotionControl(blink=1)),
                          ('speech', MotionControl(mouth_open=.5, mouth_only=True)),
                          ('smile', MotionControl(smile=.5))]:
        start = time.perf_counter()
        frame = engine.render(prepared, control)
        path = ROOT / '.tools' / f'actual-neural-{name}.png'
        cv2.imwrite(str(path), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        print(name, round(time.perf_counter() - start, 2), 'seconds', flush=True)
finally:
    engine.unload()
