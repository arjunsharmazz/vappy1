"""Small camera wrapper: opens lazily, reconnects after failures, never raises into callers.

Windows: DirectShow. Linux/Raspberry Pi: V4L2 for USB webcams; the Raspberry Pi Camera Module
(libcamera stack, which OpenCV cannot read directly) is read through `rpicam-vid` as MJPEG.
"""
import logging
import shutil
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

log = logging.getLogger("vision.camera")


JPEG_START, JPEG_END = bytes([0xFF, 0xD8]), bytes([0xFF, 0xD9])


class RpiCam:
    """Raspberry Pi Camera Module via rpicam-vid (MJPEG on stdout); keeps only the newest frame."""

    def __init__(self, width, height, fps=15):
        exe = shutil.which("rpicam-vid") or shutil.which("libcamera-vid")
        if not exe:
            raise RuntimeError("rpicam-vid not installed")
        self.process = subprocess.Popen([exe, "-t", "0", "-n", "--width", str(width), "--height", str(height),
                                         "--framerate", str(fps), "--codec", "mjpeg", "-o", "-"],
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        self.jpeg = None
        self.lock = threading.Lock()
        threading.Thread(target=self._read, name="rpicam", daemon=True).start()

    def _read(self):
        buffer = b""
        while self.process.poll() is None:
            data = self.process.stdout.read(65536)
            if not data:
                break
            buffer += data
            end = buffer.rfind(JPEG_END)
            if end < 0:
                continue
            start = buffer.rfind(JPEG_START, 0, end)
            if start >= 0:
                with self.lock:
                    self.jpeg = buffer[start:end + 2]
            buffer = buffer[end + 2:]

    def isOpened(self):
        return self.process.poll() is None

    def read(self):
        with self.lock:
            jpeg = self.jpeg
        if jpeg is None:
            return self.isOpened(), None
        return True, cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)

    def set(self, *args):
        return False

    def release(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class Camera:
    def __init__(self, index=0, width=320, height=240):
        self.index, self.width, self.height = index, width, height
        self.capture = None
        self.failures = 0
        self.retry_at = 0.0
        self.empty_reads = 0
        self.use_rpicam = False  # switched on when a V4L2 device gives no frames (Pi Camera Module)

    def _open(self):
        if self.use_rpicam:
            try:
                log.info("Opening the Raspberry Pi camera module through rpicam-vid")
                return RpiCam(self.width, self.height)
            except (OSError, RuntimeError) as error:
                log.warning("Raspberry Pi camera unavailable (%s)", error)
                return None
        # DirectShow opens laptop webcams quickly on Windows; V4L2 is the Raspberry Pi/Linux path.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_V4L2
        capture = cv2.VideoCapture(self.index, backend)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(self.index)
        if not capture.isOpened():
            capture.release()
            if sys.platform.startswith("linux") and (shutil.which("rpicam-vid") or shutil.which("libcamera-vid")):
                self.use_rpicam = True  # no USB webcam: try the camera module
                return self._open()
            return None
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # always the newest frame, low latency
        log.info("Camera %d opened", self.index)
        return capture

    def read(self):
        """Return a BGR frame resized to (width, height), or None if no camera is usable right now."""
        now = time.monotonic()
        if self.capture is None:
            if now < self.retry_at:
                return None
            self.capture = self._open()
            if self.capture is None:
                # Back off so a missing camera costs almost nothing (5 s, up to 60 s).
                self.failures += 1
                delay = min(60, 5 * self.failures)
                if self.failures == 1:
                    log.warning("No camera found at index %d; eye tracking disabled (retrying every %ds)", self.index, delay)
                self.retry_at = now + delay
                return None
            self.failures = 0
        ok, frame = self.capture.read()
        if ok and frame is None:  # rpicam-vid still starting
            return None
        if not ok or frame is None:
            self.empty_reads += 1
            # On a Pi with the camera module, /dev/video0 exists but gives no frames to OpenCV.
            if (sys.platform.startswith("linux") and not self.use_rpicam and self.empty_reads >= 3
                    and (shutil.which("rpicam-vid") or shutil.which("libcamera-vid"))):
                log.info("This camera gives no frames through V4L2; switching to rpicam-vid")
                self.use_rpicam = True
            log.warning("Camera read failed; reopening")
            self.release()
            self.retry_at = now + 2
            return None
        self.empty_reads = 0
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        return frame

    @property
    def available(self):
        return self.capture is not None

    def release(self):
        if self.capture is not None:
            self.capture.release()
            self.capture = None
            log.info("Camera released")
