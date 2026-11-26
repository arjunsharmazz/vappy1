"""One background thread owns the camera. It runs only while someone is watching the stream.

- capture thread: reads frames, finds the face with the fast detector (smooth tracking box and
  eye-gaze target at camera fps) and, while the live preview is open, keeps the newest JPEG.
- analysis thread: a few times per second reads feelings and hand gestures (analyzer.py).

Frames are processed in memory and immediately discarded; nothing is saved. The preview JPEG is
served only on this computer (127.0.0.1) to the page's camera panel.
"""
import logging
import threading
import time

import cv2

from ..settings import ROOT, get_settings
from .camera import Camera
from .face_tracker import FaceTracker, make_detector

log = logging.getLogger("vision")
YUNET = ROOT / ".tools" / "models" / "yunet" / "face_detection_yunet_2023mar.onnx"
DETECT_WIDTH = 320  # the fast detector works on a small copy; the preview keeps full size


class VisionService:
    def __init__(self, idle_stop_seconds=10.0):
        self.lock = threading.Lock()
        self.thread = None
        self.subscribers = 0
        self.preview_viewers = 0
        self.last_unsubscribe = 0.0
        self.idle_stop_seconds = idle_stop_seconds
        self.state = {"enabled": False, "camera": False, "present": False, "x": 0.0, "y": 0.0,
                      "size": 0.0, "box": None, "detector": None, "fps": 0.0, "analysis": None}
        self.version = 0
        self.frame = None
        self.frame_version = 0
        self.jpeg = None
        self.jpeg_version = 0
        self.analyzer = None
        self.analysis_at = 0.0
        self.paused = 0  # >0 while local speech recognition needs the whole CPU

    @property
    def enabled(self):
        return get_settings()["vision"]["enabled"]

    def subscribe(self, preview=False):
        with self.lock:
            self.subscribers += 1
            if preview:
                self.preview_viewers += 1
            if self.enabled and (self.thread is None or not self.thread.is_alive()):
                self.thread = threading.Thread(target=self._run, name="vision", daemon=True)
                self.thread.start()

    def unsubscribe(self, preview=False):
        with self.lock:
            self.subscribers = max(0, self.subscribers - 1)
            if preview:
                self.preview_viewers = max(0, self.preview_viewers - 1)
            self.last_unsubscribe = time.monotonic()

    def snapshot(self):
        with self.lock:
            return dict(self.state), self.version

    def latest_jpeg(self):
        with self.lock:
            return self.jpeg, self.jpeg_version

    def pause(self):
        """Context manager: stop feeling analysis while local Whisper runs (on a 2-core laptop the
        two together made a 3 s sentence take minutes). Tracking and preview keep running."""
        service = self

        class Pause:
            def __enter__(self):
                with service.lock:
                    service.paused += 1

            def __exit__(self, *exc):
                with service.lock:
                    service.paused -= 1
        return Pause()

    def describe_person(self):
        """What the person looks like right now, for the AI ('' when nobody is analysed)."""
        with self.lock:
            analyzer, present, fresh = self.analyzer, self.state.get("present"), time.monotonic() - self.analysis_at < 3
        if not analyzer or not present or not fresh:
            return ""
        return analyzer.describe()

    def _publish(self, **values):
        with self.lock:
            self.state.update(values)
            self.version += 1

    def _stopping(self):
        with self.lock:
            return self.subscribers == 0 and time.monotonic() - self.last_unsubscribe > self.idle_stop_seconds

    def _run(self):
        cfg = get_settings()["vision"]
        width, height, fps = cfg["width"], cfg["height"], max(1, cfg["fps"])
        dw = min(width, DETECT_WIDTH)
        dh = round(height * dw / width)
        camera = Camera(cfg["camera_index"], width, height)
        try:
            detector = make_detector(YUNET, dw, dh)
        except RuntimeError as error:
            log.error("No face detector available: %s", error)
            self._publish(enabled=False)
            return
        tracker = FaceTracker(detector, dw, dh)
        log.info("Vision started (camera %d, %dx%d @ %d fps, detector %s)", cfg["camera_index"], width, height, fps, detector.name)
        self._publish(enabled=True, detector=detector.name)
        stop = threading.Event()
        worker = None
        if cfg["analysis"]:
            worker = threading.Thread(target=self._analyse, args=(stop, cfg["analysis_fps"]), name="vision-analysis", daemon=True)
            worker.start()
        period, measured, last = 1.0 / fps, 0.0, time.monotonic()
        try:
            while not self._stopping():
                started = time.monotonic()
                frame = camera.read()
                if frame is None:
                    self._publish(camera=False, present=False)
                    time.sleep(0.5)
                    continue
                small = frame if dw == width else cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA)
                try:
                    result = tracker.update(small)
                except Exception:  # a detector glitch must never kill the thread
                    log.exception("Face detection failed on one frame")
                    continue
                jpeg = None
                with self.lock:
                    previewing = self.preview_viewers > 0 and cfg["preview"]
                if previewing:
                    ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72])
                    jpeg = data.tobytes() if ok else None
                now = time.monotonic()
                measured = measured * 0.9 + (1.0 / max(1e-3, now - last)) * 0.1
                last = now
                with self.lock:
                    self.frame = frame
                    self.frame_version += 1
                    if jpeg:
                        self.jpeg, self.jpeg_version = jpeg, self.jpeg_version + 1
                self._publish(camera=True, fps=round(measured, 1), resolution=[width, height], **result)
                time.sleep(max(0.0, period - (time.monotonic() - started)))
        finally:
            stop.set()
            if worker:
                worker.join(timeout=3)
            camera.release()
            with self.lock:
                self.frame, self.jpeg = None, None
            self._publish(camera=False, present=False, fps=0.0, analysis=None)
            log.info("Vision stopped (no viewers)")

    def _analyse(self, stop, rate):
        try:
            from .analyzer import Analyzer
            analyzer = Analyzer()
        except Exception:
            log.exception("Expression analysis could not start")
            return
        if not analyzer.available:
            return
        with self.lock:
            self.analyzer = analyzer
        period, seen, measured, last = 1.0 / max(0.5, rate), -1, 0.0, time.monotonic()
        try:
            while not stop.is_set():
                started = time.monotonic()
                with self.lock:
                    frame, version, state, paused = self.frame, self.frame_version, dict(self.state), self.paused
                if paused:
                    stop.wait(0.3)
                    continue
                if frame is None or version == seen or not state.get("present"):
                    if not state.get("present"):
                        self._publish(analysis=None)
                    stop.wait(0.2)
                    continue
                seen = version
                try:
                    result = analyzer.analyze(frame, tuple(state["box"]) if state.get("box") else None)
                except Exception:
                    log.exception("Expression analysis failed on one frame")
                    stop.wait(1)
                    continue
                now = time.monotonic()
                measured = measured * 0.8 + (1.0 / max(1e-3, now - last)) * 0.2
                last = now
                result["fps"] = round(measured, 1)
                with self.lock:
                    self.analysis_at = now
                self._publish(analysis=result)
                stop.wait(max(0.0, period - (time.monotonic() - started)))
        finally:
            with self.lock:
                self.analyzer = None
            analyzer.close()


service = VisionService()
