"""Instant, offline replies from config/replies.json for common phrases (English, Hindi, Hinglish).

Matching is deliberately conservative: a reply is used only when the matched phrases cover
most of what the person said, so "ok, tell me about Indian history" still goes to the LLM.
"""
from datetime import datetime
from difflib import SequenceMatcher
import json
import logging
import random
import re
import threading
import unicodedata
from pathlib import Path

from ..settings import ROOT, get_settings, persona_gender
from .style import finish, hindi_date, hindi_day, hindi_time

log = logging.getLogger("brain.replies")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
MIN_COVERAGE = 0.5
FUZZY_RATIO = 0.84


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    text = text.replace("ँ", "ं").replace("़", "")  # हूँ≈हूं, ignore nukta
    text = text.replace("।", " ").replace("॥", " ").replace("'", "").replace("’", "")
    text = re.sub(r"[^\wऀ-ॿ]+", " ", text)
    # Hinglish has no fixed spelling: achha/acha, theek/thek, dhanyawad/dhanyavaad.
    text = re.sub(r"([a-z])\1+", r"\1", text.replace("w", "v"))
    return " ".join(text.split())


def _contains(tokens, pattern):
    n = len(pattern)
    for start in range(len(tokens) - n + 1):
        if tokens[start:start + n] == pattern:
            return start
    return -1


class CannedReplies:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self.lock = threading.Lock()
        self.mtime = None
        self.intents, self.fallbacks = [], {}
        self.last = {}

    def _file(self):
        if self.path:
            return self.path
        value = Path(get_settings()["conversation"]["replies_file"])
        return value if value.is_absolute() else ROOT / value

    def _load(self):
        path = self._file()
        try:
            mtime = path.stat().st_mtime
        except OSError:
            if self.mtime is not False:
                log.warning("Replies file %s not found; ready-made replies disabled", path)
            self.mtime, self.intents, self.fallbacks = False, [], {}
            return
        if mtime == self.mtime:
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            intents = []
            for item in data.get("intents", []):
                patterns = [(lang, normalize(p).split()) for lang, values in item["patterns"].items() for p in values]
                intents.append({"id": item["id"], "patterns": [(l, p) for l, p in patterns if p],
                                "replies": item["replies"]})
            self.intents, self.fallbacks, self.mtime = intents, data.get("fallback", {}), mtime
            log.info("Loaded %d ready-made reply intents from %s", len(intents), path.name)
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            # Keep the previous good version; a typo while editing must not break conversation.
            log.error("Could not read %s (%s); keeping previous replies", path, error)
            self.mtime = mtime

    def _pick(self, key, options):
        options = [o for o in options if o] or [""]
        choice = random.choice([o for o in options if o != self.last.get(key)] or options)
        self.last[key] = choice
        return choice

    @staticmethod
    def _fill(text, user=None):
        now = datetime.now()
        hour = now.hour % 12 or 12
        female = persona_gender() == "female"
        try:
            text = text.format(name=get_settings()["persona"]["name"], user=user or "",
                               gender_en="girl" if female else "boy", gender_hi="लड़की" if female else "लड़के",
                               time=f"{hour}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}",
                               date=f"{now.day} {now.strftime('%B')} {now.year}", day=now.strftime("%A"),
                               time_hi=hindi_time(now), date_hi=hindi_date(now), day_hi=hindi_day(now))
        except (KeyError, IndexError, ValueError):
            log.warning("Unknown placeholder in reply %r", text)
        # "{user}" may be empty: tidy "Hi !" → "Hi!".
        return finish(re.sub(r"\s{2,}", " ", re.sub(r"\s+([!?.,।])", r"\1", text)).strip())

    def match(self, text: str, user: str | None = None, user_native: str | None = None):
        """Return {'intents': [...], 'language': 'en'|'hinglish', 'reply': str} or None."""
        with self.lock:
            self._load()
            norm = normalize(text)
            tokens = norm.split()
            if not tokens:
                return None
            found = []  # (score, intent, language, start, length)
            for intent in self.intents:
                best = None
                for lang, pattern in intent["patterns"]:
                    start = _contains(tokens, pattern)
                    if start >= 0:
                        candidate = (len(pattern), intent, lang, start, len(pattern))
                    else:
                        # Fuzzy match only for near-identical lengths: the ratio can never reach the
                        # threshold otherwise, and skipping keeps ~1000 patterns fast on a Raspberry Pi.
                        joined = " ".join(pattern)
                        if 2 * min(len(norm), len(joined)) < FUZZY_RATIO * (len(norm) + len(joined)):
                            continue
                        matcher = SequenceMatcher(None, norm, joined)
                        if matcher.quick_ratio() < FUZZY_RATIO:
                            continue
                        ratio = matcher.ratio()
                        if ratio < FUZZY_RATIO:
                            continue
                        candidate = (len(tokens) * ratio, intent, lang, 0, len(tokens))
                    if best is None or candidate[0] > best[0]:
                        best = candidate
                if best:
                    found.append(best)
            # Greedily keep the strongest non-overlapping matches (at most two: "hi, how are you").
            chosen, covered = [], set()
            for item in sorted(found, key=lambda f: -f[0]):
                span = set(range(item[3], item[3] + item[4]))
                if span & covered or len(chosen) == 2:
                    continue
                chosen.append(item); covered |= span
            if not chosen or len(covered) / len(tokens) < MIN_COVERAGE:
                return None
            chosen.sort(key=lambda f: f[3])
            language = "hinglish" if DEVANAGARI.search(text) or chosen[0][2] != "en" else "en"
            parts = []
            for _, intent, _, _, _ in chosen:
                replies = intent["replies"].get(language) or intent["replies"].get("en", [])
                name = user_native if language != "en" and user_native else user
                parts.append(self._fill(self._pick((intent["id"], language), replies), name))
            return {"intents": [c[1]["id"] for c in chosen], "language": language, "reply": " ".join(parts)}

    def fallback(self, text: str) -> str:
        with self.lock:
            self._load()
            language = "hinglish" if DEVANAGARI.search(text) else "en"
            options = self.fallbacks.get(language) or self.fallbacks.get("en") or ["Sorry, I didn't get that."]
            return self._fill(self._pick(("fallback", language), options))


replies = CannedReplies()
