"""Reads a person's feelings and gestures from what the camera models measure.

Inputs per analysed frame (all optional, so a missing model never breaks anything):
- MediaPipe face blendshapes (52 muscle-like values: mouthSmileLeft, browDownRight, jawOpen…)
- head pose (yaw/pitch/roll, degrees) and the face box (normalized 0..1 image coordinates)
- hand landmarks (21 points per hand) and MediaPipe's gesture names (Thumb_Up, Open_Palm…)
- an emotion classifier's probabilities (HSEmotion, AffectNet: anger, contempt, disgust, fear,
  happiness, neutral, sadness, surprise)

Output: a smoothed dominant feeling (with hysteresis, so the label does not flicker), the
active gestures/actions, and a short history. Pure logic, no models: unit-testable.
Facial cues follow common FACS descriptions (e.g. smile = lip corner pull + cheek raise,
sadness = inner brow raise + lip corner depress, anger = brow lowerer + lip press).
"""
from collections import deque
from datetime import datetime
import math

STATES = {
    "neutral": ("शांत हैं", "calm / neutral"),
    "smiling": ("मुस्कुरा रहे हैं", "smiling"),
    "laughing": ("हँस रहे हैं", "laughing"),
    "laughing_hard": ("ज़ोर से हँस रहे हैं", "laughing hard"),
    "surprised": ("हैरान हैं", "surprised"),
    "sad": ("उदास हैं", "sad"),
    "crying": ("रो रहे हैं / रोने जैसे", "crying or close to tears"),
    "angry": ("गुस्से में हैं", "angry or irritated"),
    "disgusted": ("अजीब मुँह बना रहे हैं", "making a disgusted / weird face"),
    "fearful": ("डरे हुए हैं", "scared or anxious"),
    "tense": ("टेंशन में हैं", "tense / stressed / worried"),
    "thinking": ("कुछ सोच रहे हैं", "thinking about something"),
    "tired": ("थके हुए / नींद में", "tired or sleepy (eyes closing)"),
    "yawning": ("उबासी ले रहे हैं", "yawning"),
    "confused": ("कन्फ्यूज़ हैं", "confused (one brow raised / head tilted)"),
}
GESTURES = {
    "hand_on_head": ("सिर पर हाथ", "hand on head/forehead"),
    "hand_on_chin": ("ठुड्डी पर हाथ", "hand on chin"),
    "hand_on_cheek": ("गाल पर हाथ", "hand on cheek"),
    "hand_over_mouth": ("मुँह पर हाथ", "hand over mouth"),
    "covering_face": ("चेहरा ढका", "covering face/eyes with hands"),
    "thumbs_up": ("अंगूठा ऊपर", "thumbs up"),
    "thumbs_down": ("अंगूठा नीचे", "thumbs down"),
    "victory": ("विक्ट्री साइन", "victory / peace sign"),
    "waving": ("हाथ हिला रहे हैं", "waving hello"),
    "open_palm": ("खुली हथेली", "showing an open palm"),
    "pointing_up": ("उंगली ऊपर", "pointing up"),
    "fist": ("मुट्ठी", "closed fist raised"),
    "love_you": ("आई लव यू साइन", "I-love-you hand sign"),
    "nodding": ("हाँ में सिर हिलाया", "nodding yes"),
    "shaking_head": ("ना में सिर हिलाया", "shaking head no"),
    "talking": ("बोल रहे हैं", "talking"),
    "eyes_closed": ("आँखें बंद", "eyes closed"),
    "looking_away": ("इधर-उधर देख रहे हैं", "looking away"),
    "head_tilt": ("सिर टेढ़ा", "head tilted"),
    "showing_fingers": ("उंगलियाँ दिखा रहे हैं", "showing fingers"),
}
MP_GESTURES = {"Thumb_Up": "thumbs_up", "Thumb_Down": "thumbs_down", "Victory": "victory",
               "Open_Palm": "open_palm", "Pointing_Up": "pointing_up", "Closed_Fist": "fist",
               "ILoveYou": "love_you"}
CLASSES = ("anger", "contempt", "disgust", "fear", "happiness", "neutral", "sadness", "surprise")
TIPS = (4, 8, 12, 16, 20)
PALM = (0, 5, 9, 13, 17)
HINDI_NUMBERS = ["शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ", "दस"]


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def count_fingers(points):
    """Open fingers on one hand (0-5) from its 21 landmarks: a finger is open when its tip is
    clearly farther from the wrist than its middle joint; the thumb when its tip is far from
    the palm (beside the index knuckle and away from the little-finger knuckle)."""
    if len(points) < 21:
        return 0
    wrist, size = points[0], max(1e-3, _dist(points[0], points[9]))
    count = 0
    for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)):
        if _dist(points[tip], wrist) > _dist(points[pip], wrist) * 1.12:
            count += 1
    thumb_out = _dist(points[4], points[17]) > _dist(points[3], points[17]) * 1.08 \
        and _dist(points[4], points[5]) > 0.38 * size
    return count + (1 if thumb_out else 0)


def _label(name):
    if name.startswith("fingers_"):
        n = int(name.split("_")[1])
        return f"{HINDI_NUMBERS[n] if n <= 10 else n} {'उंगली' if n == 1 else 'उंगलियाँ'}"
    return (STATES.get(name) or GESTURES.get(name) or (name,))[0]


def clip(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def ramp(value, start, width):
    """0 below `start`, rising linearly to 1 at `start + width`."""
    return clip((value - start) / width)


def features(blend):
    b = lambda name: float(blend.get(name, 0.0))
    pair = lambda name: (b(name + "Left") + b(name + "Right")) / 2
    return {"smile": pair("mouthSmile"), "jaw": b("jawOpen"), "brow_down": pair("browDown"),
            "brow_inner_up": b("browInnerUp"), "brow_outer_up": pair("browOuterUp"),
            "brow_asym": abs(b("browOuterUpLeft") - b("browOuterUpRight")), "blink": pair("eyeBlink"),
            "squint": pair("eyeSquint"), "wide": pair("eyeWide"), "frown": pair("mouthFrown"),
            "press": pair("mouthPress"), "sneer": pair("noseSneer"), "upper_up": pair("mouthUpperUp"),
            "pucker": b("mouthPucker"), "cheek": pair("cheekSquint"),
            "look_up": pair("eyeLookUp")}


def hand_gestures(hands, face_box):
    """Where the hands are relative to the face. hands: list of 21 (x, y) points, 0..1."""
    found = set()
    if not hands or not face_box:
        return found
    x0, y0, x1, y1 = face_box
    w, h = max(1e-3, x1 - x0), max(1e-3, y1 - y0)
    cx = (x0 + x1) / 2
    on_face = 0
    for points in hands:
        if len(points) < 21:
            continue
        px = sum(points[i][0] for i in PALM) / 5
        py = sum(points[i][1] for i in PALM) / 5
        top_tip = min(points[i][1] for i in TIPS)
        dx = abs(px - cx) / w
        if dx < 1.0 and top_tip < y0 + 0.2 * h and py < y0 + 0.45 * h:
            found.add("hand_on_head")
        elif dx < 0.38 and y0 + 0.2 * h <= py <= y1 - 0.05 * h:
            on_face += 1
            # Palm over the mouth area vs over the eyes/nose.
            found.add("hand_over_mouth" if py > y0 + 0.62 * h else "covering_face")
        elif dx < 0.55 and y1 - 0.2 * h <= py <= y1 + 0.4 * h:
            found.add("hand_on_chin")
        elif 0.3 <= dx < 0.95 and y0 + 0.35 * h <= py <= y1 + 0.1 * h:
            found.add("hand_on_cheek")
    if on_face >= 2:
        found.discard("hand_over_mouth")
        found.add("covering_face")
    return found


def oscillates(values, min_range, min_turns=2):
    """True when a signal swings back and forth (nod, head shake, wave)."""
    if len(values) < 5 or max(values) - min(values) < min_range:
        return False
    turns, direction = 0, 0
    for a, b in zip(values, values[1:]):
        step = b - a
        if abs(step) < min_range * 0.15:
            continue
        sign = 1 if step > 0 else -1
        if direction and sign != direction:
            turns += 1
        direction = sign
    return turns >= min_turns


class ExpressionReader:
    def __init__(self, tau=0.7, switch_margin=0.08, hold_seconds=0.6):
        self.tau, self.switch_margin, self.hold_seconds = tau, switch_margin, hold_seconds
        self.smooth = {name: 0.0 for name in STATES}
        self.classes = {name: 0.0 for name in CLASSES}
        self.dominant, self.since, self.candidate, self.candidate_since = "neutral", None, None, None
        self.last = None
        self.jaw, self.pitch, self.yaw, self.palm_x = (deque(maxlen=n) for n in (12, 10, 10, 10))
        self.blink_ema, self.look_up_since = 0.0, None
        self.gestures, self.gesture_since = set(), {}
        self.finger_count, self.finger_since, self.fingers_shown = None, None, None
        self.finger_per_hand = []
        self.events = deque(maxlen=12)

    def set_classifier(self, probs):
        """Emotion classifier output (runs less often); blended into the next updates."""
        for name, value in zip(CLASSES, probs):
            self.classes[name] = self.classes[name] * 0.4 + float(value) * 0.6

    def update(self, now, blend=None, pose=None, face_box=None, hands=None, hand_names=()):
        dt = 0.25 if self.last is None else clip(now - self.last, 0.01, 1.0)
        self.last = now
        f = features(blend or {})
        c = self.classes
        yaw, pitch, roll = pose or (0.0, 0.0, 0.0)
        self.jaw.append(f["jaw"])
        if pose:
            self.pitch.append(pitch); self.yaw.append(yaw)
        self.blink_ema += (f["blink"] - self.blink_ema) * clip(dt / 1.2)

        gestures = hand_gestures(hands or [], face_box)
        self._count_fingers(now, hands or [], hand_names)
        if self.fingers_shown is not None:
            gestures.add("showing_fingers")
        for name in hand_names:
            if name in MP_GESTURES:
                gestures.add(MP_GESTURES[name])
        if hands:
            self.palm_x.append(sum(hands[0][i][0] for i in PALM) / 5)
        else:
            self.palm_x.clear()
        if "open_palm" in gestures and oscillates(list(self.palm_x), 0.05):
            gestures.add("waving")
        jaw_list = list(self.jaw)
        mean_jaw = sum(jaw_list) / len(jaw_list)
        spread = math.sqrt(sum((j - mean_jaw) ** 2 for j in jaw_list) / len(jaw_list))
        talking = blend is not None and len(jaw_list) >= 6 and spread > 0.05 and mean_jaw < 0.45
        if talking:
            gestures.add("talking")
        if blend is not None and self.blink_ema > 0.6:
            gestures.add("eyes_closed")
        if pose and oscillates(list(self.pitch), 7):
            gestures.add("nodding")
        if pose and oscillates(list(self.yaw), 9):
            gestures.add("shaking_head")
        if pose and (abs(yaw) > 28 or abs(pitch) > 22):
            gestures.add("looking_away")
        if pose and abs(roll) > 14:
            gestures.add("head_tilt")
        looking_up = blend is not None and f["look_up"] > 0.35 and not talking
        self.look_up_since = (self.look_up_since or now) if looking_up else None
        looked_up_long = self.look_up_since is not None and now - self.look_up_since > 1.2

        mouth = 0.45 if talking else 1.0  # speech opens the mouth: not laughing/yawning/surprise
        smile, jaw = f["smile"], f["jaw"]
        not_smiling = 1 - ramp(smile, 0.2, 0.3)
        g = lambda name: 1.0 if name in gestures else 0.0
        raw = {
            "neutral": 0.22 + 0.3 * c["neutral"],
            "smiling": ramp(smile, 0.25, 0.35) * (1 - 0.5 * ramp(jaw, 0.25, 0.3)) + 0.3 * c["happiness"],
            # A wide-open laughing mouth is "laughing hard", not just laughing.
            "laughing": ramp(smile, 0.35, 0.3) * ramp(jaw, 0.12, 0.2) * (1 - 0.5 * ramp(jaw, 0.4, 0.3)) * mouth
                        + 0.15 * c["happiness"],
            "laughing_hard": ramp(smile, 0.5, 0.3) * ramp(jaw, 0.35, 0.25) * (0.7 + 0.3 * ramp(f["squint"], 0.2, 0.4)) * mouth,
            "surprised": (0.4 * ramp(f["wide"], 0.15, 0.35) + 0.3 * ramp(max(f["brow_inner_up"], f["brow_outer_up"]), 0.3, 0.4)
                          + 0.3 * ramp(jaw, 0.15, 0.4) * mouth) * not_smiling + 0.45 * c["surprise"] + 0.25 * g("hand_over_mouth"),
            "sad": (0.5 * ramp(f["frown"], 0.08, 0.3) + 0.3 * ramp(f["brow_inner_up"], 0.2, 0.4)) * not_smiling + 0.5 * c["sadness"],
            "angry": (0.5 * ramp(f["brow_down"], 0.25, 0.35) + 0.25 * ramp((f["sneer"] + f["press"]) / 2, 0.15, 0.3)) * not_smiling
                     + 0.5 * c["anger"],
            "disgusted": (0.5 * ramp(f["sneer"], 0.15, 0.35) + 0.2 * ramp(f["upper_up"], 0.2, 0.4)) * not_smiling
                         + 0.5 * (c["disgust"] + c["contempt"]),
            "fearful": 0.6 * c["fear"] + 0.4 * f["wide"] * f["brow_inner_up"],
            "tense": (0.35 * ramp(f["brow_down"], 0.2, 0.4) + 0.25 * ramp(f["press"], 0.15, 0.35)) * not_smiling
                     + 0.8 * g("hand_on_head") + 0.35 * g("covering_face"),
            "thinking": 0.75 * max(g("hand_on_chin"), g("hand_on_cheek")) + 0.5 * looked_up_long + 0.15 * f["pucker"],
            "tired": 0.85 * ramp(self.blink_ema, 0.45, 0.35) * not_smiling,
            "yawning": ramp(jaw, 0.55, 0.3) * not_smiling * (0.5 if talking else 1.0) + 0.3 * g("hand_over_mouth") * ramp(jaw, 0.3, 0.3),
            "confused": 0.6 * ramp(f["brow_asym"], 0.2, 0.3) + 0.3 * g("head_tilt") * ramp(f["brow_down"], 0.1, 0.3),
        }
        sad_now = clip(raw["sad"])
        raw["crying"] = sad_now * ramp((self.blink_ema + f["squint"]) / 2, 0.3, 0.4) + 0.6 * g("covering_face") * not_smiling * (0.5 + sad_now)
        raw["sad"] = sad_now * (1 - 0.35 * clip(raw["crying"]))  # tears are more than sadness
        alpha = clip(dt / self.tau)
        for name, value in raw.items():
            self.smooth[name] += (clip(value) - self.smooth[name]) * alpha
        self._choose(now)
        self._track_gestures(now, gestures)
        return self.result(now, f, (yaw, pitch, roll) if pose else None)

    def _choose(self, now):
        best = max(self.smooth, key=self.smooth.get)
        if self.since is None:
            self.since = now
        if best == self.dominant or self.smooth[best] < self.smooth[self.dominant] + self.switch_margin:
            self.candidate = None
            return
        if best != self.candidate:
            self.candidate, self.candidate_since = best, now
        elif now - self.candidate_since >= self.hold_seconds:
            self.events.append((datetime.now().strftime("%H:%M:%S"), best, round(self.smooth[best], 2)))
            self.dominant, self.since, self.candidate = best, now, None

    def _count_fingers(self, now, hands, hand_names):
        """Total open fingers on all visible hands; 'stable' once unchanged for ~1 s, so a
        hand moving into place is not read as a number."""
        if not hands or any(n in ("Thumb_Up", "Thumb_Down") for n in hand_names):
            self.finger_count, self.finger_since, self.fingers_shown = None, None, None
            self.finger_per_hand = []
            return
        self.finger_per_hand = [count_fingers(points) for points in hands]
        total = sum(self.finger_per_hand)
        if total != self.finger_count:
            self.finger_count, self.finger_since = total, now
        if now - self.finger_since >= 0.9 and total >= 1:
            if self.fingers_shown != total:
                self.events.append((datetime.now().strftime("%H:%M:%S"), f"fingers_{total}", 1.0))
            self.fingers_shown = total
        elif total == 0:
            self.fingers_shown = None

    def _track_gestures(self, now, gestures):
        for name in gestures - self.gestures:
            self.gesture_since[name] = now
            if name not in ("talking", "looking_away", "head_tilt", "eyes_closed", "showing_fingers"):
                self.events.append((datetime.now().strftime("%H:%M:%S"), name, 1.0))
        for name in self.gestures - gestures:
            self.gesture_since.pop(name, None)
        self.gestures = gestures

    def result(self, now, f=None, pose=None):
        top = sorted(self.smooth.items(), key=lambda kv: -kv[1])[:5]
        return {
            "emotion": self.dominant, "emotion_hi": STATES[self.dominant][0],
            "confidence": round(self.smooth[self.dominant], 2),
            "emotion_seconds": round(now - self.since, 1) if self.since is not None else 0.0,
            "scores": {k: round(v, 2) for k, v in top},
            "gestures": sorted(self.gestures),
            "gestures_hi": [GESTURES[g][0] for g in sorted(self.gestures) if g in GESTURES],
            "head": [round(v, 1) for v in pose] if pose else None,
            "classifier": {k: round(v, 2) for k, v in sorted(self.classes.items(), key=lambda kv: -kv[1])[:3]},
            "fingers": {"total": self.finger_count, "shown": self.fingers_shown,
                        "per_hand": self.finger_per_hand} if self.finger_count is not None else None,
            "events": [{"time": t, "name": n, "label": _label(n), "score": s}
                       for t, n, s in list(self.events)[-8:]],
        }

    def describe(self, now):
        """One line for the AI: what the person looks like right now and just before."""
        if self.last is None or now - self.last > 3:
            return ""
        parts = [f"look {STATES[self.dominant][1]}"]
        cues = [GESTURES[g][1] for g in sorted(self.gestures) if g in GESTURES and g not in ("looking_away", "showing_fingers")]
        if self.fingers_shown:
            cues.append(f"holding up {self.fingers_shown} finger{'s' if self.fingers_shown != 1 else ''}")
        if cues:
            parts.append("(" + ", ".join(cues) + ")")
        seconds = now - self.since if self.since is not None else 0
        if seconds >= 3:
            parts.append(f"for about {int(seconds)} s")
        earlier = [n for _, n, _ in list(self.events)[:-1] if n in STATES and n != self.dominant]
        if earlier:
            parts.append(f"; a little earlier: {STATES[earlier[-1]][1]}")
        return " ".join(parts)
