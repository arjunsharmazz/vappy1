"""Local persistence with read compatibility for Phase 1 flat JSON records."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import cv2
from fastapi import HTTPException
from .face_landmarks import WARNING


def create_avatar(encoded, face_detected, details, uploads: Path, root: Path):
    avatar_id = str(uuid4())
    folder = root / avatar_id
    image = uploads / f"{avatar_id}.jpg"
    record = {
        "success": True, "avatar_id": avatar_id, "face_detected": face_detected,
        "status": "ready" if face_detected else "no_face",
        "message": "Avatar Ready" if face_detected else "No face detected. Please upload a clear front-facing photo.",
        "image_url": f"/avatar/{avatar_id}/image",
        "created_at": datetime.now(timezone.utc).isoformat(), "schema_version": 2, **details,
    }
    try:
        folder.mkdir()
        (folder / "original.jpg").write_bytes(encoded)
        # Retain Phase 1 /uploads URLs for callers that already use that route.
        image.write_bytes(encoded)
        (folder / "avatar.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    except OSError:
        for path in (image, folder / "original.jpg", folder / "avatar.json"):
            path.unlink(missing_ok=True)
        if folder.exists():
            folder.rmdir()
        raise
    return record


def read_avatar(avatar_id: str, uploads: Path, root: Path):
    try:
        if str(UUID(avatar_id)) != avatar_id:
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(400, "Invalid avatar_id.")
    folder = root / avatar_id
    record_path = folder / "avatar.json"
    legacy = False
    if not record_path.exists():
        record_path = root / f"{avatar_id}.json"
        legacy = True
    if not record_path.is_file():
        raise HTTPException(404, "Avatar not found.")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8-sig"))
        if not isinstance(record, dict) or record.get("avatar_id") != avatar_id or not isinstance(record.get("face_detected"), bool):
            raise ValueError("Invalid metadata")
        if not legacy and (not isinstance(record.get("landmarks"), dict) or not isinstance(record.get("animation_available"), bool)):
            raise ValueError("Invalid animation metadata")
    except (OSError, ValueError):
        raise HTTPException(422, "Avatar metadata is unreadable or corrupted.")
    image = uploads / f"{avatar_id}.jpg" if legacy else folder / "original.jpg"
    if not image.is_file():
        raise HTTPException(404, "Avatar image is missing.")
    # Decode on retrieval so corrupted files produce a helpful API error.
    try:
        from numpy import frombuffer, uint8
        decoded = cv2.imdecode(frombuffer(image.read_bytes(), dtype=uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            raise ValueError("Invalid image")
    except (OSError, ValueError, cv2.error):
        raise HTTPException(422, "Avatar image is corrupted.")
    if legacy:
        record.update(animation_available=False, landmarks={}, face_box=None,
                      image_width=decoded.shape[1], image_height=decoded.shape[0],
                      warning=WARNING if record["face_detected"] else None)
    record.update(success=True, status="ready" if record["face_detected"] else "no_face",
                  image_url=f"/avatar/{avatar_id}/image")
    return record, image
