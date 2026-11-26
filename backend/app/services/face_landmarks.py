"""Facial regions in saved-image pixels; left/right mean viewer's left/right.

1. MediaPipe face landmarks (exact eyes and lips; works with glasses, tilt, smiles, beards)
2. OpenCV Haar eye cascade (the original method; often misses eyes)
3. Typical face proportions inside the detected face box, so a portrait is never left without
   animation only because the eye detector failed (the neural engine finds its own keypoints;
   these regions only shape the blend masks).
"""
import logging
import threading

import cv2
import numpy as np

from ..settings import ROOT

WARNING = "Avatar created, but advanced facial animation is unavailable for this photo."
log = logging.getLogger("landmarks")
FACE_MODEL = ROOT / ".tools" / "models" / "vision" / "face_landmarker.task"
_MP = {"landmarker": None, "failed": False}
_MP_LOCK = threading.Lock()


def _landmarker():
    if _MP["landmarker"] is None and not _MP["failed"]:
        try:
            from mediapipe.tasks.python import vision, BaseOptions
            _MP["landmarker"] = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(FACE_MODEL)), running_mode=vision.RunningMode.IMAGE,
                num_faces=1, min_face_detection_confidence=.3, min_face_presence_confidence=.3))
        except Exception as error:  # library or model missing: older methods still work
            _MP["failed"] = True
            log.warning("MediaPipe face landmarks unavailable (%s); using Haar eyes", error)
    return _MP["landmarker"]


def mediapipe_landmarks(image):
    """Eyes, mouth and a square face box from MediaPipe's 478-point face mesh (BGR image)."""
    if not FACE_MODEL.is_file():
        return {}, None
    import mediapipe as mp
    with _MP_LOCK:
        landmarker = _landmarker()
        if landmarker is None:
            return {}, None
        rgb = np.ascontiguousarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        found = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not found.face_landmarks:
        return {}, None
    h, w = image.shape[:2]
    pts = np.array([(p.x * w, p.y * h) for p in found.face_landmarks[0]], np.float64)

    def eye(outer, inner, upper, lower):
        a, b = pts[outer], pts[inner]
        span = float(np.hypot(*(a - b)))
        cx, cy = (a + b) / 2
        cy = (cy + (pts[upper][1] + pts[lower][1]) / 2) / 2
        # Same scale as the Haar path (eye box * .8 / * .42) so the masks behave the same.
        return {"x": float(cx), "y": float(cy), "width": span * 1.2, "height": span * .6, "source": "mediapipe"}
    first, second = eye(33, 133, 159, 145), eye(263, 362, 386, 374)
    left, right = (first, second) if first["x"] < second["x"] else (second, first)
    oval = pts[[10, 152, 234, 454]]
    face_w = float(np.hypot(*(pts[454] - pts[234])))
    face_h = float(np.hypot(*(pts[152] - pts[10])))
    mouth_x = float((pts[61][0] + pts[291][0]) / 2)
    mouth_y = float((pts[13][1] + pts[14][1]) / 2)
    mouth = {"x": mouth_x, "y": mouth_y, "width": max(float(np.hypot(*(pts[291] - pts[61]))) * 1.15, face_w * .3),
             "height": max(float(np.hypot(*(pts[17] - pts[0]))), face_h * .1), "source": "mediapipe"}
    # A square box like the Haar face detector's (forehead to chin), for when Haar finds no face.
    cx, cy = float(oval[:, 0].mean()), float(oval[:, 1].mean())
    side = max(face_w, face_h) * 1.1
    box = (cx - side / 2, cy - side * .55, side, side)
    return {"left_eye": left, "right_eye": right, "mouth": mouth, "face_center": {"x": cx, "y": cy}}, box


def proportional_landmarks(face):
    """Last resort: where eyes and mouth usually are inside a frontal face box."""
    x, y, w, h = [float(v) for v in face]
    eye = lambda fx: {"x": x + fx * w, "y": y + .40 * h, "width": .22 * w, "height": .11 * w, "source": "proportional"}
    return {"left_eye": eye(.31), "right_eye": eye(.69),
            "mouth": {"x": x + .5 * w, "y": y + .80 * h, "width": .36 * w, "height": .12 * h, "source": "proportional"},
            "face_center": {"x": x + w / 2, "y": y + h / 2}}


def extract_landmarks(gray, face):
    x, y, w, h = [int(v) for v in face]
    classifier = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")
    if classifier.empty():
        raise RuntimeError("Eye cascade unavailable")
    region = gray[y:y + int(h * .62), x:x + w]
    eyes = classifier.detectMultiScale(region, 1.1, 4,
        minSize=(max(8, int(w * .10)), max(8, int(h * .10))),
        maxSize=(int(w * .42), int(h * .38)))
    candidates = []
    for ex, ey, ew, eh in eyes:
        cx, cy = ex + ew / 2, ey + eh / 2
        if .12 * w < cx < .88 * w and .18 * h < cy < .57 * h:
            candidates.append((float(cx), float(cy), float(ew), float(eh)))
    pairs = []
    for left in candidates:
        for right in candidates:
            gap = right[0] - left[0]
            if .22 * w < gap < .65 * w and abs(left[1] - right[1]) < .13 * h:
                # Prefer near-level eyes, a plausible separation, and similar sizes.
                score = abs(left[1] - right[1]) + abs(gap - .4 * w) + abs(left[2] - right[2])
                pairs.append((score, left, right))
    if not pairs:
        return {}
    _, left, right = min(pairs, key=lambda pair: pair[0])
    def eye(value):
        cx, cy, ew, eh = value
        return {"x": x + cx, "y": y + cy, "width": ew * .8, "height": eh * .42, "source": "haar"}
    # Search below the nose: the former upper range could mistake nostrils for lips.
    mx = float(np.clip(x + (left[0] + right[0]) / 2, x + .35*w, x + .65*w))
    y0, y1 = y + int(h * .74), y + int(h * .94)
    x0, x1 = int(mx - w * .14), int(mx + w * .14)
    strip = gray[y0:y1, x0:x1]
    my = y + h * .83
    if strip.size:
        row_means = strip.mean(axis=1)
        row_means = np.convolve(np.pad(row_means, (2, 2), mode="edge"), np.ones(5)/5, mode="valid")
        my = float(y0 + int(np.argmin(row_means)))
    return {
        "left_eye": eye(left), "right_eye": eye(right),
        "mouth": {"x": mx, "y": my, "width": w * .36, "height": h * .12, "source": "estimated"},
        "face_center": {"x": x + w / 2, "y": y + h / 2},
    }
