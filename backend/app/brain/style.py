"""How the avatar's words are finished before they are spoken.

- Gender: replies are written in the masculine form; a female persona gets feminine Hindi
  verbs (करता हूँ → करती हूँ, रखूँगा → रखूँगी). Only first-person patterns are changed.
- Hindi time and date for the Hindi voice ("रात के 9 बजकर 15 मिनट", "सोमवार, 9 नवंबर 2026").
"""
from datetime import datetime
import re

from ..settings import get_settings, persona_gender

FEMININE = [
    (re.compile(r"ता (हूँ|हूं)"), r"ती \1"), (re.compile(r"ूँगा"), "ूँगी"), (re.compile(r"ूंगा"), "ूंगी"),
    (re.compile(r"रहा (हूँ|हूं)"), r"रही \1"), (re.compile(r"रहा था"), "रही थी"), (re.compile(r"समझा नहीं"), "समझी नहीं"),
    (re.compile(r"नया (हूँ|हूं)"), r"नई \1"), (re.compile(r"नहीं खाता"), "नहीं खाती"), (re.compile(r"सकता(?! है)"), "सकती"),
    (re.compile(r"नहीं पाया"), "नहीं पाई"), (re.compile(r"रहूँगा"), "रहूँगी"),
    (re.compile(r"\b(\w+)ta hoon\b"), r"\1ti hoon"), (re.compile(r"\b(\w+)unga\b"), r"\1ungi"),
    (re.compile(r"\braha (hoon|tha)\b"), lambda m: "rahi " + ("hoon" if m.group(1) == "hoon" else "thi")),
    (re.compile(r"\bsamjha nahi\b"), "samjhi nahi"), (re.compile(r"\bsakta(?! hai)\b"), "sakti"),
    (re.compile(r"\bnaya hoon\b"), "nayi hoon"), (re.compile(r"\bnahi khata\b"), "nahi khati"),
]
DAYS = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]
MONTHS = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def finish(text: str) -> str:
    if persona_gender() == "female":
        for pattern, replacement in FEMININE:
            text = pattern.sub(replacement, text)
    return text


def hindi_time(now: datetime | None = None) -> str:
    now = now or datetime.now()
    hour = now.hour % 12 or 12
    part = "सुबह" if 5 <= now.hour < 12 else "दोपहर" if 12 <= now.hour < 16 else "शाम" if 16 <= now.hour < 20 else "रात"
    return f"{part} के {hour} बजे" if now.minute == 0 else f"{part} के {hour} बजकर {now.minute} मिनट"


def hindi_day(now: datetime | None = None) -> str:
    return DAYS[(now or datetime.now()).weekday()]


def hindi_date(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{now.day} {MONTHS[now.month - 1]} {now.year}"
