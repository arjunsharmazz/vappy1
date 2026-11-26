"""Commands that need data or memory (run before ready-made replies and the LLM).

- Name:   "my name is Arjun" / "mera naam Arjun hai" / "मेरा नाम अर्जुन है", and "what is my name?"
- Notes:  "remember that I like tea" / "yaad rakhna ki ..." and "what do you remember?" / "sab bhool jao"
- News:   "today's news" / "aaj ki khabar" / "समाचार" (internet if available, else last saved copy)
- Maths:  "what is 12 times 4" / "5 plus 3 kitna hota hai" / "१० भाग २"
Replies are English for English input, Roman-script Hinglish otherwise (the current voice is English).
"""
from datetime import datetime
import re
import time
import unicodedata

from .canned_replies import replies
from .memory import memory
from .news import headlines
from .style import finish, hindi_date
from .translit import to_roman
from ..settings import get_settings

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINDI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
HINGLISH_HINTS = re.compile(r"\b(mera|meri|mujhe|kya|hai|hain|hoon|ho|naam|yaad|batao|bata|kitna|kitne|aaj|ki|ka|ke|khabar|samachar|sab|tum|tumhe|aap)\b")
NAME_ASK_COOLDOWN = 600

GET_NAME = re.compile(r"(what(?: is|s)? my name|do you (?:know|remember) my name|who am i\b|"
                      r"mera naam (?:kya|batao|bata)|mujhe jaante ho|main kaun hoon|"
                      r"मेरा नाम (?:क्या|बताओ)|मैं कौन हूँ|मैं कौन हूं|मुझे जानते हो)")
SET_NAME = [
    re.compile(r"\b(?:my name is|my names|call me|i am called)\s+(.+)$"),
    re.compile(r"\bmera naam\s+(.+?)(?:\s+(?:hai|he|h))?$"),
    re.compile(r"\bmujhe\s+(.+?)\s+(?:bulao|bulaya karo|kaho)$"),
    re.compile(r"मेरा नाम\s+(.+?)(?:\s+(?:है|हैं))?$"),
    re.compile(r"मुझे\s+(.+?)\s+(?:बुलाओ|कहो)$"),
]
# Everyday words that must never be saved as somebody's name.
NOT_NAMES = set("kya nahi nahin na haan han ha pata malum kuch kaun kab kaise kahan kyun aur ya to bhi abhi kal aaj what no yes not dont know who why how when where the a an and or but sorry wait ruko achha acha theek thik क्या नहीं हाँ हां पता कुछ कौन".split())
NAME_FILLERS = re.compile(r"\b(?:hai|he|hoon|hu|hun|ji|please|plz|main|mai|i am|im|its|it is|naam|is|है|हूँ|हूं|जी|मैं)\b")
REMEMBER = [
    re.compile(r"\bremember (?:that )?(.+)$"),
    re.compile(r"\byaad rakh(?:na|o|iye|ना)?(?: ki| ke)? (.+)$"),
    re.compile(r"^(.+?) yaad rakh(?:na|o|iye)?$"),
    re.compile(r"याद रख(?:ना|ो|िए)?(?: कि)? (.+)$"),
    re.compile(r"^(.+?) याद रख(?:ना|ो|िए)?$"),
]
RECALL = re.compile(r"(what do you remember|what do you know about me|tumhe kya yaad hai|kya yaad hai|"
                    r"mere baare mein kya pata|तुम्हें क्या याद है|क्या याद है|मेरे बारे में क्या पता)")
FORGET = re.compile(r"(forget (?:me|everything)|sab bhool jao|sab kuch bhool jao|सब भूल जाओ)")
NEWS = re.compile(r"\b(news|headlines?|khabar|khabre|khabrein|samachar|taza khabar)\b|खबर|ख़बर|समाचार|न्यूज")
# "I have good news" / "ek achhi khabar hai" is the person sharing news, not asking for headlines.
OWN_NEWS = re.compile(r"\b(good|great|bad|sad|achhi|acchi|achi|buri)\s+(news|khabar)\b|अच्छी (खबर|ख़बर)|बुरी (खबर|ख़बर)")
OPERATORS = [
    (r"\b(?:plus|add|jama|jod|joda|प्लस|जमा)\b|\+", "+"),
    (r"\b(?:minus|subtract|ghata|ghatao|माइनस|घटा)\b|−", "-"),
    (r"\b(?:times|into|multiplied by|multiply|guna|गुणा)\b|[x×*]", "*"),
    (r"\b(?:divided by|divide by|divide|bhag|by|भाग)\b|[÷/]", "/"),
]
MATH = re.compile(r"(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)")


def _clean(text):
    text = unicodedata.normalize("NFC", text.lower()).translate(HINDI_DIGITS)
    text = text.replace("'", "").replace("’", "")  # what's → whats, I'm → im
    text = re.sub(r"[?!।,\"“”]+", " ", text)
    return " ".join(text.split())


def language_of(text, clean):
    return "hinglish" if DEVANAGARI.search(text) or HINGLISH_HINTS.search(clean) else "en"


def _say(lang, en, hindi):
    """English for English input; Devanagari Hindi otherwise (the Hindi voice reads Roman
    Hinglish with an English accent). Feminine verbs are applied for a female persona."""
    return finish(en if lang == "en" else hindi)


def native_name(raw):
    """The name as heard in Devanagari ("अर्जुन"), so the Hindi voice says it naturally."""
    words = [w for w in NAME_FILLERS.sub(" ", raw).split() if DEVANAGARI.search(w)]
    return " ".join(words) if 1 <= len(words) <= 3 else None


def spoken_name(data, lang):
    return (data.get("user_name_native") if lang != "en" else None) or data["user_name"]


def clean_name(raw):
    raw = NAME_FILLERS.sub(" ", raw.strip(" .'\""))
    words = [w for w in raw.split() if w]
    if not 1 <= len(words) <= 3 or any(len(w) > 20 for w in words):
        return None
    if any(w in NOT_NAMES for w in words):
        return None
    name = " ".join(words)
    if DEVANAGARI.search(name):
        name = to_roman(name)
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", name):
        return None
    return " ".join(w.capitalize() for w in name.split())


SWAP = {"i": "you", "im": "you're", "me": "you", "my": "your", "mine": "yours", "myself": "yourself", "am": "are",
        "mujhe": "aapko", "mera": "aapka", "meri": "aapki", "mere": "aapke", "main": "aap", "mai": "aap",
        "maine": "aapne", "mujhse": "aapse", "hoon": "ho", "hu": "ho",
        "मुझे": "आपको", "मेरा": "आपका", "मेरी": "आपकी", "मेरे": "आपके", "मैं": "आप", "मैंने": "आपने", "मुझसे": "आपसे"}


def second_person(note):
    """Notes are saved as the person said them ("mujhe chai pasand hai"); read back as "aapko ..."."""
    return " ".join(SWAP.get(w, w) for w in note.split())


def _maths(clean):
    expression = clean
    for pattern, symbol in OPERATORS:
        expression = re.sub(pattern, f" {symbol} ", expression)
    match = MATH.search(expression)
    if not match:
        return None
    a, op, b = float(match.group(1)), match.group(2), float(match.group(3))
    if op == "/" and b == 0:
        return "zero"
    value = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0}[op]
    fmt = lambda v: str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")
    names = {"+": "plus", "-": "minus", "*": "times", "/": "divided by"}
    return f"{fmt(a)} {names[op]} {fmt(b)} is {fmt(value)}", fmt(value)


def _news(lang):
    titles, fetched, fresh = headlines("en" if lang == "en" else "hi")
    if not titles:
        return _say(lang, "I can't get the news right now because there's no internet connection.",
                    "अभी इंटरनेट नहीं है, इसलिए मैं न्यूज़ नहीं बता सकता।")
    joined = "। ".join(f"{i}. {t}" for i, t in enumerate(titles, 1)) if lang != "en" else \
        ". ".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
    if fresh:
        return _say(lang, f"Here are today's top headlines. {joined}.", f"आज की कुछ ख़ास ख़बरें। {joined}।")
    when_en = time.strftime("%d %B", time.localtime(fetched)) if fetched else ""
    when_hi = hindi_date(datetime.fromtimestamp(fetched)).rsplit(" ", 1)[0] if fetched else ""
    return _say(lang, f"I'm offline, but here are the last headlines I saved on {when_en}. {joined}.",
                f"अभी इंटरनेट नहीं है, पर {when_hi} की सेव की हुई ख़बरें ये हैं। {joined}।")


def handle(avatar_id, text):
    """Return {'intents': [...], 'reply': str} for a data/memory command, else None."""
    clean = _clean(text)
    lang = language_of(text, clean)
    data = memory.load(avatar_id)
    pending = memory.peek_pending(avatar_id)

    if FORGET.search(clean):
        memory.forget(avatar_id)
        return {"intents": ["forget"], "reply": _say(lang, "Okay, I've forgotten what you told me.", "ठीक है, मैंने सब भुला दिया।")}
    if GET_NAME.search(clean):
        if data["user_name"]:
            return {"intents": ["get_name"], "reply": _say(lang, f"Your name is {data['user_name']}!", f"आपका नाम {spoken_name(data, lang)} है!")}
        memory.ask(avatar_id, "name")
        return {"intents": ["get_name"], "reply": _say(lang, "You haven't told me yet. What's your name?", "आपने अभी तक बताया नहीं। आपका नाम क्या है?")}
    # Speech often gets cut after "mera naam…" — ask for the rest instead of guessing.
    if re.fullmatch(r"(?:my name is|my name|mera naam|mera nam|मेरा नाम)(?: (?:hai|है|is))?", clean):
        memory.ask(avatar_id, "name")
        return {"intents": ["set_name"], "reply": _say(lang, "Yes? What's your name?", "हाँ जी, आपका नाम?")}
    # Look for the name clause by clause: "My name is Arjun, Laila Arjun" → "Arjun", not three words
    # that include a second, misheard phrase.
    clauses = [_clean(part) for part in re.split(r"[,.!?।;]", text) if part.strip()]
    for pattern in SET_NAME:
        match = next((m for m in (pattern.search(c) for c in clauses) if m), None)
        if match and (name := clean_name(match.group(1))):
            native = native_name(match.group(1))
            memory.set_name(avatar_id, name, native)
            said = native if lang != "en" and native else name
            return {"intents": ["set_name"], "reply": _say(lang, f"Nice to meet you, {name}! I'll remember your name.",
                                                           f"आपसे मिलकर बहुत अच्छा लगा, {said}! मैं आपका नाम याद रखूँगा।")}
    # A short answer right after "what's your name?" is the name — unless it is a known phrase
    # ("theek hai", "ok", "thank you"), which must not become someone's name.
    if pending == "name" and len(clean.split()) <= 4 and replies.match(text) is None:
        raw = re.sub(r"\b(my name is|mera naam)\b|मेरा नाम", " ", clean)
        if name := clean_name(raw):
            native = native_name(raw)
            memory.set_name(avatar_id, name, native)
            said = native if lang != "en" and native else name
            return {"intents": ["set_name"], "reply": _say(lang, f"Nice to meet you, {name}!", f"आपसे मिलकर अच्छा लगा, {said}!")}
    if RECALL.search(clean):
        facts = ([_say(lang, f"your name is {data['user_name']}", f"आपका नाम {spoken_name(data, lang)} है")] if data["user_name"] else []) + \
                [second_person(n) for n in data["notes"]]
        if not facts:
            return {"intents": ["recall"], "reply": _say(lang, "You haven't asked me to remember anything yet.", "आपने अभी तक मुझे कुछ याद रखने को नहीं कहा।")}
        return {"intents": ["recall"], "reply": _say(lang, "I remember that ", "मुझे याद है कि ") + "; ".join(facts) + "."}
    for pattern in REMEMBER:
        match = pattern.search(clean)
        if match and len(match.group(1)) >= 3:
            memory.add_note(avatar_id, match.group(1).strip(" ."))
            return {"intents": ["remember"], "reply": _say(lang, "Okay, I'll remember that.", "ठीक है, मैं यह याद रखूँगा।")}
    if NEWS.search(clean) and not OWN_NEWS.search(clean) and len(clean.split()) <= 10:
        return {"intents": ["news"], "reply": _news(lang)}
    maths = _maths(clean)
    if maths:
        if maths == "zero":
            return {"intents": ["maths"], "reply": _say(lang, "We can't divide by zero!", "ज़ीरो से भाग नहीं दे सकते!")}
        sentence, value = maths
        return {"intents": ["maths"], "reply": _say(lang, f"{sentence}.", f"जवाब है {value}।")}
    return None


def maybe_ask_name(avatar_id, intents, lang):
    """After a greeting from someone whose name we don't know, ask for it (at most every 10 min)."""
    if "greeting" not in intents or memory.load(avatar_id)["user_name"]:
        return ""
    now = time.monotonic()
    if now - memory.last_asked.get(avatar_id, -NAME_ASK_COOLDOWN) < NAME_ASK_COOLDOWN:
        return ""
    memory.last_asked[avatar_id] = now
    memory.ask(avatar_id, "name")
    return _say(lang, " What's your name?", " आपका नाम क्या है?")


def greeting(avatar_id, ask_name=False):
    """What the avatar says when someone walks up to the frame (Hindi voice). With ask_name
    (app start-up) it always asks, because a different person may be in front of the frame;
    whatever name is said next replaces the saved one."""
    data = memory.load(avatar_id)
    avatar = get_settings()["persona"]["name"]
    if data["user_name"] and not ask_name:
        return finish(f"नमस्ते {spoken_name(data, 'hi')}! आपको देखकर बहुत अच्छा लगा।")
    memory.ask(avatar_id, "name")
    memory.last_asked[avatar_id] = time.monotonic()
    return finish(f"नमस्ते! मैं {avatar} हूँ। आपका नाम क्या है?")


def unclear(text):
    """Polite request to repeat, used when speech recognition was unsure."""
    clean = _clean(text)
    return _say(language_of(text, clean), "Sorry, I couldn't hear that clearly. Could you say it again, a little slowly?",
                "माफ़ कीजिए, मैं ठीक से सुन नहीं पाया। एक बार फिर से, थोड़ा धीरे बोलिए?")


def stt_hotwords(avatar_id):
    """Names Whisper should spell correctly ("Arjun", not "Arjan"), passed as hotwords.
    Never a sentence: with a sentence prompt Whisper wrote "Aap kaise ho? Kya chal raha hai?"
    for plain room noise (measured), so the avatar answered things nobody said."""
    try:
        data = memory.load(avatar_id)
    except ValueError:
        data = {"user_name": None, "user_name_native": None}
    words = [w.strip() for w in get_settings()["stt"]["hint_words"].split(",") if w.strip()]
    for name in (data.get("user_name"), data.get("user_name_native")):
        if name and name not in words:
            words.append(name)
    return ", ".join(words) or None


def facts_for_prompt(avatar_id):
    from .profile import facts_text
    data = memory.load(avatar_id)
    facts = ([f"The person's name is {data['user_name']}."] if data["user_name"] else []) + \
            [f"The person told you: {n}." for n in data["notes"][-8:]]
    learned = facts_text(data)  # what the avatar picked up in earlier conversations
    return " ".join(facts + ([learned] if learned else []))
