"""Guess whether a portrait shows a man or a woman, to pick the avatar's voice and Hindi verb
forms (Swara/करती हूँ vs Madhur/करता हूँ). Offline: the ONNX model zoo's age_gender GoogLeNet,
run on the face crop at two zoom levels and mirrored (averaged for stability). The photo never
leaves the computer. A guess can be wrong, so the person can switch it in the menu
(POST /avatar/{id}/voice); that choice is stored as "voice_gender" and always wins.
"""
import json
import logging
import threading

import cv2
import numpy as np

from ..settings import ROOT

log = logging.getLogger("gender")
MODEL = ROOT / ".tools" / "models" / "vision" / "gender_googlenet.onnx"
MEAN = np.array([104, 117, 123], np.float32)  # Caffe-style BGR mean (checked on known portraits)
_STATE = {"session": None, "failed": False}
_LOCK = threading.Lock()


def _session():
    if _STATE["session"] is None and not _STATE["failed"]:
        try:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            _STATE["session"] = ort.InferenceSession(str(MODEL), options, providers=["CPUExecutionProvider"])
        except Exception as error:
            _STATE["failed"] = True
            log.warning("Gender model unavailable (%s); the default persona voice is used", error)
    return _STATE["session"]


def classify(image, face_box):
    """image: BGR; face_box: {x, y, width, height} in image pixels.
    Returns ('male' | 'female', confidence 0.5-1) or (None, 0.0)."""
    if not MODEL.is_file() or not face_box:
        return None, 0.0
    with _LOCK:
        session = _session()
        if session is None:
            return None, 0.0
        h, w = image.shape[:2]
        cx, cy = face_box["x"] + face_box["width"] / 2, face_box["y"] + face_box["height"] / 2
        probs = []
        for pad in (1.0, 1.4):
            side = max(face_box["width"], face_box["height"]) * pad
            x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
            x1, y1 = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
            if x1 - x0 < 24 or y1 - y0 < 24:
                continue
            face = cv2.resize(image[y0:y1, x0:x1], (224, 224), interpolation=cv2.INTER_AREA).astype(np.float32) - MEAN
            for view in (face, face[:, ::-1]):
                out = session.run(None, {session.get_inputs()[0].name: np.ascontiguousarray(view.transpose(2, 0, 1)[None])})[0][0]
                e = np.exp(out - out.max())
                probs.append(e / e.sum())
    if not probs:
        return None, 0.0
    male, female = np.mean(probs, axis=0)
    return ("male", round(float(male), 2)) if male >= female else ("female", round(float(female), 2))


def avatar_gender(avatar_id, root):
    """The avatar's voice gender: the person's own choice, else the photo guess, else None."""
    try:
        record = json.loads((root / avatar_id / "avatar.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    value = record.get("voice_gender") or record.get("gender")
    return value if value in ("male", "female") else None
