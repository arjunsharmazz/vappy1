"""Ready-made avatars shipped with the project (the `avtars/` folder).

On a PC, `backend/scripts/prepare_avatars.py` turns every photo in `avtars/` into a bundle in
`avtars/prepared/<name>/`: the processed photo, its record (face, eyes, mouth, man/woman) and its
neural face poses (atlas, WebP to keep the repository small). When the backend starts (on the PC
or on a Raspberry Pi) the bundles are copied into avatar_data/ once, so these avatars open with a
fully prepared face immediately — the Pi never has to run the slow, hot neural engine.
"""
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cv2

from ..config import AVATAR_DATA, ROOT

log = logging.getLogger("library")
LIBRARY = ROOT / "avtars"
PREPARED = LIBRARY / "prepared"
ATLASES = AVATAR_DATA / "neural_atlases"
IMAGE_TYPES = {".jpg", ".jpeg", ".jfif", ".jpe", ".png", ".webp"}


def bundles():
    if not PREPARED.is_dir():
        return []
    found = []
    for folder in sorted(PREPARED.iterdir()):
        record = folder / "avatar.json"
        if folder.is_dir() and record.is_file() and (folder / "original.jpg").is_file():
            try:
                found.append((folder, json.loads(record.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                log.warning("Skipping unreadable avatar bundle %s", folder.name)
    return found


def _install_atlas(folder, key):
    """Write the bundle's poses into the neural atlas cache (PNG, as the engine would)."""
    png, manifest = ATLASES / f"{key}.png", ATLASES / f"{key}.json"
    if png.is_file() and manifest.is_file():
        return True
    source = folder / "atlas.webp"
    if not source.is_file() or not (folder / "atlas.json").is_file():
        return False
    image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
    if image is None:
        log.warning("Prepared poses of %s could not be read", folder.name)
        return False
    ATLASES.mkdir(parents=True, exist_ok=True)
    pending = png.with_suffix(".pending.png")
    cv2.imwrite(str(pending), image)
    pending.replace(png)
    shutil.copyfile(folder / "atlas.json", manifest)
    return True


def install(folder, record):
    """Copy one bundle into avatar_data/ (idempotent) and return the avatar id."""
    avatar_id = record["avatar_id"]
    target = AVATAR_DATA / avatar_id
    if not (target / "avatar.json").is_file():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(folder / "original.jpg", target / "original.jpg")
        stored = {**record, "created_at": record.get("created_at") or datetime.now(timezone.utc).isoformat()}
        (target / "avatar.json").write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding="utf-8")
    if record.get("prepared_atlas"):
        _install_atlas(folder, record["prepared_atlas"])
    return avatar_id


def install_all():
    installed = []
    for folder, record in bundles():
        try:
            installed.append(install(folder, record))
        except (OSError, KeyError) as error:
            log.warning("Could not install avatar %s (%s)", folder.name, error)
    if installed:
        log.info("Ready-made avatars available: %d", len(installed))
    return installed


def listing():
    """For the avatar picker: id, name, man/woman, image."""
    return [{"avatar_id": r["avatar_id"], "name": r.get("library_name") or folder.name,
             "gender": r.get("voice_gender") or r.get("gender"), "image_url": f"/avatar/{r['avatar_id']}/image"}
            for folder, r in bundles()]


def prepared_atlas(record):
    """The cache key of a library avatar's ready poses (re-installed if the cache dropped it)."""
    key = record.get("prepared_atlas")
    if not key:
        return None
    if not (ATLASES / f"{key}.png").is_file():
        for folder, bundle in bundles():
            if bundle.get("avatar_id") == record.get("avatar_id"):
                _install_atlas(folder, key)
    return key if (ATLASES / f"{key}.png").is_file() else None
