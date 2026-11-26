"""Prepare the ready-made avatars in avtars/ (run on a PC, once, after adding photos).

For every photo in avtars/ this finds the face, eyes and mouth, guesses man/woman (voice), renders
the neural face poses (~8 min per new photo on a laptop CPU), and writes a bundle to
avtars/prepared/<name>/ that the backend installs automatically — on this PC and on a Raspberry Pi,
where the neural engine is too slow and hot to run. Commit avtars/ (including prepared/) to git.

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\prepare_avatars.py          (Windows)
    backend/.venv/bin/python backend/scripts/prepare_avatars.py                      (Linux)

Already prepared photos are skipped (same file contents); use --force to redo them.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import AVATAR_DATA  # noqa: E402
from app.imaging import process_image  # noqa: E402
from app.services.avatar_library import LIBRARY, PREPARED, IMAGE_TYPES, ATLASES  # noqa: E402

NAMESPACE = uuid5(NAMESPACE_URL, "living-frame-avatar-library")


def slug(name):
    text = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return text or "avatar"


def display_name(stem):
    text = re.sub(r"[_\-]+", " ", stem)
    text = re.sub(r"\(\d+\)|\d+$", "", text).strip()
    return text.title() or stem


def wait_for_atlas(avatar_id, image, metadata):
    from app.services.neural_avatar.engine_manager import manager
    job = manager.start(avatar_id, image, metadata, AVATAR_DATA / avatar_id / "neural", "ATLAS", "balanced", duration=1)
    last = -1
    while job["state"] not in ("READY", "ERROR", "CANCELLED"):
        time.sleep(2)
        job = manager.status(job["job_id"], avatar_id)
        percent = int((job.get("progress") or 0) * 100)
        if percent != last and percent % 10 == 0:
            print(f"    poses {percent}%", flush=True)
            last = percent
    if job["state"] != "READY":
        raise RuntimeError(job.get("error") or job["state"])
    return job["cache_key"]


def prepare(path, force=False):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    name = slug(path.stem)
    bundle = PREPARED / name
    record_path = bundle / "avatar.json"
    if record_path.is_file() and not force:
        old = json.loads(record_path.read_text(encoding="utf-8"))
        if old.get("source_sha256") == digest and (bundle / "atlas.webp").is_file():
            print(f"  {path.name}: already prepared")
            return True
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)  # .jfif/.webp too
    if image is None:
        print(f"  {path.name}: not a readable photo — skipped")
        return False
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    encoded, face, details = process_image(jpeg.tobytes(), ".jpg")
    if not face or not details.get("animation_available"):
        print(f"  {path.name}: no usable face found — skipped")
        return False
    avatar_id = str(uuid5(NAMESPACE, digest))
    record = {"success": True, "avatar_id": avatar_id, "face_detected": True, "status": "ready", "message": "Avatar Ready",
              "image_url": f"/avatar/{avatar_id}/image", "schema_version": 2, **details,
              "library_name": display_name(path.stem), "source_file": path.name, "source_sha256": digest}
    # The engine renders from avatar_data/<id>/original.jpg, like for an uploaded photo.
    folder = AVATAR_DATA / avatar_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "original.jpg").write_bytes(encoded)
    (folder / "avatar.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {path.name}: face found ({details.get('gender') or '?'} voice) — preparing neural poses…", flush=True)
    key = wait_for_atlas(avatar_id, folder / "original.jpg", record)
    record["prepared_atlas"] = key
    (folder / "avatar.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    bundle.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(folder / "original.jpg", bundle / "original.jpg")
    atlas = cv2.imread(str(ATLASES / f"{key}.png"), cv2.IMREAD_UNCHANGED)
    # WebP keeps the transparency and is ~10x smaller than the PNG cache file (repository size).
    cv2.imwrite(str(bundle / "atlas.webp"), atlas, [cv2.IMWRITE_WEBP_QUALITY, 92])
    shutil.copyfile(ATLASES / f"{key}.json", bundle / "atlas.json")
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    size = sum(f.stat().st_size for f in bundle.iterdir()) / 1e6
    print(f"  {path.name}: ready → avtars/prepared/{name} ({size:.1f} MB)")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="prepare again even if unchanged")
    args = parser.parse_args()
    photos = sorted(p for p in LIBRARY.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_TYPES) if LIBRARY.is_dir() else []
    if not photos:
        print(f"No photos in {LIBRARY}")
        return
    print(f"Preparing {len(photos)} photo(s) from {LIBRARY}")
    done = 0
    try:
        for photo in photos:
            try:
                done += prepare(photo, args.force)
            except Exception as error:
                print(f"  {photo.name}: failed ({error})")
    finally:
        from app.services.neural_avatar.engine_manager import manager
        manager.shutdown()
    print(f"Done: {done}/{len(photos)} ready. Commit the avtars/ folder (including avtars/prepared/).")


if __name__ == "__main__":
    main()
