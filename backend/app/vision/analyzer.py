"""Runs the camera models on a frame: MediaPipe face landmarks (+52 blendshapes, head pose),
MediaPipe hand gestures and the HSEmotion facial-expression classifier, then lets
ExpressionReader turn the numbers into a feeling and gestures.

Heavy for an old laptop CPU (~43 + 64 + 82 ms measured on an i5-4300U), so the face runs every
analysed frame, hands every 2nd and the classifier every 3rd. Any missing model or library just
disables that part. Frames stay in memory only.
"""
import logging
import math
import time

import cv2
import numpy as np

from ..settings import ROOT
from .expressions import ExpressionReader

log = logging.getLogger("vision.analyzer")
MODELS = ROOT / ".tools" / "models" / "vision"

# MediaPipe face-mesh indices for drawing the outline of the face in the live preview.
CONTOURS = {
    "oval": [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
             148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10],
    "left_eye": [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466, 263],
    "right_eye": [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246, 33],
    "left_brow": [276, 283, 282, 295, 285, 300, 293, 334, 296, 336],
    "right_brow": [46, 53, 52, 65, 55, 70, 63, 105, 66, 107],
    "lips": [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185, 61],
    "inner_lips": [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191, 78],
    "nose": [168, 6, 197, 195, 5, 4, 1, 19, 94, 2],
}
MESH_SAMPLE = list(range(0, 468, 9))
EMOTION_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
EMOTION_STD = np.array([0.229, 0.224, 0.225], np.float32)


def head_pose(matrix):
    """Yaw (left/right), pitch (up/down), roll (tilt) in degrees from MediaPipe's face transform."""
    r = np.asarray(matrix, dtype=np.float64)[:3, :3]
    yaw = math.degrees(math.asin(clamp(-r[2, 0], -1, 1)))
    pitch = math.degrees(math.atan2(r[2, 1], r[2, 2]))
    roll = math.degrees(math.atan2(r[1, 0], r[0, 0]))
    return yaw, pitch, roll


def clamp(v, a, b):
    return max(a, min(b, v))


class Analyzer:
    def __init__(self):
        self.reader = ExpressionReader()
        self.face = self.hands = self.emotion = None
        self.count = 0
        self.started = time.monotonic()
        self.timings = {}
        self.hand_points, self.hand_names = [], []
        self._load()

    @property
    def available(self):
        return self.face is not None or self.emotion is not None

    def _load(self):
        try:
            from mediapipe.tasks.python import vision, BaseOptions
            face_model, hand_model = MODELS / "face_landmarker.task", MODELS / "gesture_recognizer.task"
            if face_model.is_file():
                self.face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(face_model)), running_mode=vision.RunningMode.VIDEO,
                    num_faces=1, output_face_blendshapes=True, output_facial_transformation_matrixes=True))
            if hand_model.is_file():
                self.hands = vision.GestureRecognizer.create_from_options(vision.GestureRecognizerOptions(
                    base_options=BaseOptions(model_asset_path=str(hand_model)), running_mode=vision.RunningMode.VIDEO,
                    num_hands=2))
        except Exception as error:  # ImportError or a broken model file
            log.warning("MediaPipe unavailable (%s); face expressions and hand gestures disabled", error)
        try:
            import onnxruntime as ort
            model = MODELS / "enet_b0_8_best_afew.onnx"
            if model.is_file():
                options = ort.SessionOptions()
                options.intra_op_num_threads = 1  # leave the CPU for speech and the browser
                self.emotion = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
                self.emotion_input = self.emotion.get_inputs()[0].name
        except Exception as error:
            log.warning("Emotion classifier unavailable (%s)", error)
        log.info("Expression analysis: face=%s hands=%s emotion=%s", self.face is not None,
                 self.hands is not None, self.emotion is not None)

    def _timed(self, name, fn):
        started = time.perf_counter()
        try:
            return fn()
        finally:
            ms = (time.perf_counter() - started) * 1000
            self.timings[name] = round(self.timings.get(name, ms) * 0.7 + ms * 0.3, 1)

    def analyze(self, frame, fallback_box=None):
        """frame: BGR image. fallback_box: (x0, y0, x1, y1) 0..1 from the fast face detector,
        used when the face mesh is lost (e.g. hands covering the face)."""
        import mediapipe as mp
        self.count += 1
        now = time.monotonic()
        stamp = int((now - self.started) * 1000)
        rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        blend = pose = box = None
        contours, mesh = {}, []
        if self.face is not None:
            found = self._timed("face_ms", lambda: self.face.detect_for_video(image, stamp))
            if found.face_landmarks:
                points = found.face_landmarks[0]
                xs, ys = [p.x for p in points[:468]], [p.y for p in points[:468]]
                box = (min(xs), min(ys), max(xs), max(ys))
                contours = {k: [[round(points[i].x, 4), round(points[i].y, 4)] for i in idx] for k, idx in CONTOURS.items()}
                mesh = [[round(points[i].x, 4), round(points[i].y, 4)] for i in MESH_SAMPLE]
                if len(points) >= 478:
                    contours["irises"] = [[round(points[i].x, 4), round(points[i].y, 4)] for i in (468, 473)]
                if found.face_blendshapes:
                    blend = {b.category_name: b.score for b in found.face_blendshapes[0]}
                if found.facial_transformation_matrixes:
                    pose = head_pose(found.facial_transformation_matrixes[0])
        face_box = box or fallback_box
        if self.hands is not None and (self.hand_points or self.count % 2 == 0):
            result = self._timed("hands_ms", lambda: self.hands.recognize_for_video(image, stamp))
            self.hand_points = [[(round(p.x, 4), round(p.y, 4)) for p in hand] for hand in result.hand_landmarks]
            self.hand_names = [g[0].category_name for g in result.gestures if g and g[0].score > 0.6]
        if self.emotion is not None and face_box is not None and self.count % 3 == 1:
            crop = self._crop(rgb, face_box)
            if crop is not None:
                logits = self._timed("emotion_ms", lambda: self.emotion.run(None, {self.emotion_input: crop})[0][0])
                e = np.exp(logits - logits.max())
                self.reader.set_classifier(e / e.sum())
        state = self.reader.update(now, blend, pose, face_box, self.hand_points, self.hand_names)
        state.update({"face_box": [round(v, 4) for v in face_box] if face_box else None,
                      "contours": contours, "mesh": mesh, "hands": self.hand_points, "timings": dict(self.timings)})
        return state

    @staticmethod
    def _crop(rgb, box):
        h, w = rgb.shape[:2]
        x0, y0, x1, y1 = box
        cx, cy, side = (x0 + x1) / 2 * w, (y0 + y1) / 2 * h, max((x1 - x0) * w, (y1 - y0) * h) * 1.15
        a, b = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
        c, d = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
        if c - a < 24 or d - b < 24:
            return None
        face = cv2.resize(rgb[b:d, a:c], (224, 224), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
        return ((face - EMOTION_MEAN) / EMOTION_STD).transpose(2, 0, 1)[None].astype(np.float32)

    def describe(self):
        return self.reader.describe(time.monotonic())

    def close(self):
        for model in (self.face, self.hands):
            try:
                if model is not None:
                    model.close()
            except Exception:
                pass
