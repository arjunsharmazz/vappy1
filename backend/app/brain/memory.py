"""Long-term memory per avatar: the person's name and a few things they asked to remember.

Stored as avatar_data/<avatar_id>/memory.json (local only). Writes are atomic so a power cut
on the Raspberry Pi cannot leave a half-written file. A short-lived "pending question" (the
avatar just asked for the name) lives only in RAM.
"""
import json
import logging
import threading
import time
from pathlib import Path
from uuid import UUID

from ..config import AVATAR_DATA

log = logging.getLogger("brain.memory")
MAX_NOTES = 20
PENDING_SECONDS = 90


class MemoryStore:
    def __init__(self, root: Path = AVATAR_DATA):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.pending = {}  # avatar_id -> (question, expires_at)
        self.last_asked = {}  # avatar_id -> monotonic time the name was last asked

    def _path(self, avatar_id):
        UUID(avatar_id)  # never build a path from anything but a UUID
        return self.root / avatar_id / "memory.json"

    def load(self, avatar_id):
        path = self._path(avatar_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("user_name", None)
                data.setdefault("user_name_native", None)
                data["notes"] = [n for n in data.get("notes", []) if isinstance(n, str)][-MAX_NOTES:]
                return data
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            log.warning("Memory for %s unreadable (%s); starting fresh", avatar_id, error)
        return {"user_name": None, "user_name_native": None, "notes": []}

    def _save(self, avatar_id, data):
        path = self._path(avatar_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        pending = path.with_suffix(".pending.json")
        pending.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        pending.replace(path)

    def set_name(self, avatar_id, name, native=None):
        with self.lock:
            data = self.load(avatar_id)
            data["user_name"] = name
            data["user_name_native"] = native
            self._save(avatar_id, data)
            self.pending.pop(avatar_id, None)  # the name question is answered
            log.info("Remembered the person's name")

    def add_note(self, avatar_id, note):
        with self.lock:
            data = self.load(avatar_id)
            if note not in data["notes"]:
                data["notes"] = (data["notes"] + [note])[-MAX_NOTES:]
            self._save(avatar_id, data)

    def forget(self, avatar_id):
        with self.lock:
            self._save(avatar_id, {"user_name": None, "user_name_native": None, "notes": []})
            self.pending.pop(avatar_id, None)

    def ask(self, avatar_id, question):
        self.pending[avatar_id] = (question, time.monotonic() + PENDING_SECONDS)

    def peek_pending(self, avatar_id):
        """The open question stays open until answered or expired, even if the person first
        says something else ("how are you?") before giving their name."""
        question, expires = self.pending.get(avatar_id, (None, 0))
        if question and time.monotonic() >= expires:
            self.pending.pop(avatar_id, None)
            return None
        return question

    def clear_pending(self, avatar_id):
        self.pending.pop(avatar_id, None)


memory = MemoryStore()
