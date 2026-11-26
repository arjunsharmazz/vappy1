"""Find the main viewer's face and turn it into a stable, normalized target.

Output coordinates: x, y in [-1, 1] relative to the frame centre (+x = right side of the
camera image, +y = down), and `size` = face width / frame width. Presence uses hysteresis
so a missed detection or a person briefly turning away does not flip the avatar to idle.
"""
import logging
import time
from pathlib import Path

import cv2

log = logging.getLogger("vision.tracker")


class YuNetDetector:
    name = "yunet"

    def __init__(self, model: Path, width, height):
        self.net = cv2.FaceDetectorYN.create(str(model), "", (width, height), 0.7, 0.3, 50)

    def detect(self, frame):
        _, faces = self.net.detect(frame)
        if faces is None:
            return []
        return [(float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])) for f in faces]


class HaarDetector:
    """Fallback bundled with OpenCV: no download needed, faster, but noisier."""
    name = "haar"

    def __init__(self):
        self.cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if self.cascade.empty():
            raise RuntimeError("Haar face cascade unavailable")

    def detect(self, frame):
        gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        found = self.cascade.detectMultiScale(gray, 1.15, 5, minSize=(30, 30))
        return [(float(x), float(y), float(w), float(h), 1.0) for x, y, w, h in found]


def make_detector(model: Path, width, height):
    if model.is_file():
        try:
            return YuNetDetector(model, width, height)
        except cv2.error as error:
            log.warning("YuNet model could not be loaded (%s); using Haar fallback", error)
    else:
        log.warning("YuNet model missing at %s; using Haar fallback", model)
    return HaarDetector()


class FaceTracker:
    def __init__(self, detector, width, height, appear_seconds=0.3, leave_seconds=2.0, smoothing=0.35):
        self.detector, self.width, self.height = detector, width, height
        self.appear_seconds, self.leave_seconds, self.smoothing = appear_seconds, leave_seconds, smoothing
        self.present = False
        self.first_seen = None
        self.last_seen = 0.0
        self.x = self.y = 0.0
        self.size = 0.0
        self.box = None  # (x0, y0, x1, y1) in 0..1, smoothed: the live preview's tracking box
        self.score = 0.0

    def update(self, frame, now=None):
        now = time.monotonic() if now is None else now
        faces = self.detector.detect(frame)
        if faces:
            # The largest face is usually the person closest to the frame.
            x, y, w, h, score = max(faces, key=lambda f: f[2] * f[3])
            tx = (x + w / 2) / self.width * 2 - 1
            ty = (y + h / 2) / self.height * 2 - 1
            size = w / self.width
            box = (x / self.width, y / self.height, (x + w) / self.width, (y + h) / self.height)
            self.score = score
            if self.first_seen is None or self.box is None:
                self.box = box
            else:
                # Follows quickly (the box should stick to the face) but without jitter.
                self.box = tuple(old + (new - old) * 0.6 for old, new in zip(self.box, box))
            if self.first_seen is None:
                self.first_seen = now
                self.x, self.y, self.size = tx, ty, size
            else:
                # Light smoothing only; the browser adds natural eye dynamics on top.
                a = self.smoothing
                self.x += (tx - self.x) * a
                self.y += (ty - self.y) * a
                self.size += (size - self.size) * a
            self.last_seen = now
            if not self.present and now - self.first_seen >= self.appear_seconds:
                self.present = True
                log.info("Person detected")
        else:
            if self.present and now - self.last_seen > self.leave_seconds:
                self.present = False
                log.info("Person left; avatar goes idle")
            if not self.present:
                self.first_seen = None
            if now - self.last_seen > 0.5:
                self.box = None
        return self.state(now)

    def state(self, now=None):
        now = time.monotonic() if now is None else now
        return {"present": self.present, "x": round(self.x, 4), "y": round(self.y, 4),
                "size": round(self.size, 4), "seen_ago": round(now - self.last_seen, 2) if self.last_seen else None,
                "box": [round(v, 4) for v in self.box] if self.box else None, "score": round(self.score, 2)}
