"""Tiny Devanagari → Roman transliteration, so names heard in Hindi can be spoken by the
current English voice ("अर्जुन" → "Arjun"). Good enough for names, not a full scheme."""

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
}
VOWELS = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
          "ओ": "o", "औ": "au"}
MATRAS = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au"}
HALANT, NUKTA = "्", "़"
NASAL = {"ं": "n", "ँ": "n", "ः": "h"}


def _word(word):
    out, i = [], 0
    chars = list(word)
    while i < len(chars):
        c = chars[i]
        if i + 1 < len(chars) and chars[i + 1] == NUKTA:
            c += NUKTA; i += 1
        if c in CONSONANTS:
            out.append(CONSONANTS[c])
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if nxt in MATRAS:
                out.append(MATRAS[nxt]); i += 1
            elif nxt == HALANT:
                i += 1
            elif i + 1 < len(chars):
                out.append("a")  # inherent vowel; dropped at the end of a word (schwa deletion)
        elif c in VOWELS:
            out.append(VOWELS[c])
        elif c in NASAL:
            out.append(NASAL[c])
        elif c.isascii():
            out.append(c)
        i += 1
    return "".join(out)


def to_roman(text: str) -> str:
    return " ".join(_word(w).capitalize() for w in text.split() if w)
