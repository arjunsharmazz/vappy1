"""Bounded, CPU-only face detection using OpenCV's bundled Haar cascade."""
import os
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", "20000000")

import logging
import cv2
import numpy as np
from fastapi import HTTPException

from .services.gender import classify as classify_gender
from .services.face_landmarks import extract_landmarks, mediapipe_landmarks, proportional_landmarks, WARNING

cv2.setNumThreads(2)

def process_image(data: bytes, suffix: str):
    png = data.startswith(b"\x89PNG\r\n\x1a\n")
    jpeg = data.startswith(b"\xff\xd8\xff")
    if not ((suffix == ".png" and png) or (suffix in {".jpg", ".jpeg"} and jpeg)):
        raise HTTPException(415, "File contents must match a JPG, JPEG or PNG image.")
    try:
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        raise HTTPException(422, "Image could not be decoded or exceeds the 20 megapixel limit.")
    if image is None:
        raise HTTPException(422, "Image could not be decoded. Please choose another photo.")
    height, width = image.shape[:2]
    if height * width > 20_000_000:
        raise HTTPException(413, "Image must be no larger than 20 megapixels.")
    scale = min(1.0, 1600 / max(height, width))
    if scale < 1:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 800 / max(gray.shape))
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    detection_scale = gray.shape[1] / image.shape[1]
    gray = cv2.equalizeHist(gray)
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if detector.empty():
        raise RuntimeError("Could not load the bundled face detector.")
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    details = {"image_width": image.shape[1], "image_height": image.shape[0],
               "face_box": None, "landmarks": {}, "animation_available": False,
               "landmark_method": "haar_eyes_estimated_mouth", "warning": None}
    # Exact eyes/lips first (MediaPipe); it also finds faces the Haar detector misses.
    try:
        precise, precise_box = mediapipe_landmarks(image)
    except Exception:
        logging.exception("MediaPipe landmarks failed; using Haar")
        precise, precise_box = {}, None
    if precise:
        if len(faces):
            face = max(faces, key=lambda f: int(f[2]) * int(f[3]))
            box = tuple(float(v / detection_scale) for v in face)
        else:
            box = precise_box
        details.update(face_box=dict(zip(("x", "y", "width", "height"), box)), landmarks=precise,
                       animation_available=True, landmark_method="mediapipe_face_mesh")
    elif len(faces):
        face = max(faces, key=lambda f: int(f[2]) * int(f[3]))
        details["face_box"] = dict(zip(("x", "y", "width", "height"),
                                     (float(v / detection_scale) for v in face)))
        try:
            landmarks = extract_landmarks(gray, face)
            for point in landmarks.values():
                for key in ("x", "y", "width", "height"):
                    if key in point:
                        point[key] /= detection_scale
            details["landmarks"] = landmarks
            details["animation_available"] = bool(landmarks)
        except Exception:
            logging.exception("Landmark extraction failed; preserving valid portrait")
        if not details["animation_available"]:
            # Eyes not found: typical proportions keep the portrait animated anyway.
            box = details["face_box"]
            details["landmarks"] = proportional_landmarks((box["x"], box["y"], box["width"], box["height"]))
            details["animation_available"] = True
            details["landmark_method"] = "face_proportions"
    if details["face_box"]:
        try:
            details["gender"], details["gender_confidence"] = classify_gender(image, details["face_box"])
        except Exception:
            logging.exception("Gender guess failed; the default voice is used")
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("Could not encode image.")
    return encoded.tobytes(), len(faces) > 0 or bool(precise), details

