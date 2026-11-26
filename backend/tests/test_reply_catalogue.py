import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.brain import skills
from app.brain.canned_replies import CannedReplies
from app.brain.memory import memory
from app.settings import ROOT


class CatalogueTests(unittest.TestCase):
    """The ready-made catalogue (config/replies.json) stays large, consistent and speakable."""

    @classmethod
    def setUpClass(cls):
        cls.r = CannedReplies(ROOT / "config" / "replies.json")
        cls.r._load()

    def test_has_at_least_100_questions_with_both_reply_languages(self):
        self.assertGreaterEqual(len(self.r.intents), 100)
        for intent in self.r.intents:
            self.assertTrue(intent["replies"].get("en"), intent["id"])
            self.assertTrue(intent["replies"].get("hinglish"), intent["id"])

    def test_first_pattern_of_each_language_reaches_its_intent(self):
        for intent in self.r.intents:
            seen = set()
            for lang, tokens in intent["patterns"]:
                if lang in seen:
                    continue
                seen.add(lang)
                got = self.r.match(" ".join(tokens))
                self.assertIsNotNone(got, (intent["id"], tokens))
                self.assertIn(intent["id"], got["intents"], (intent["id"], tokens))

    def test_hindi_replies_are_devanagari_and_fully_filled(self):
        for intent in self.r.intents:
            for reply in intent["replies"]["hinglish"]:
                out = self.r._fill(reply, "अर्जुन")
                self.assertRegex(out, "[ऀ-ॿ]", intent["id"])
                self.assertNotIn("{", out, intent["id"])

    def test_sharing_good_news_is_not_a_headline_request(self):
        got = self.r.match("ek achhi khabar hai")
        self.assertEqual(got["intents"], ["good_news"])
        with tempfile.TemporaryDirectory() as folder, patch.object(memory, "root", Path(folder)):
            self.assertIsNone(skills.handle(str(uuid4()), "ek achhi khabar hai"))


class StartGreetingTests(unittest.TestCase):
    def test_start_always_asks_name_even_if_known(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(memory, "root", Path(folder)):
            avatar = str(uuid4())
            memory.set_name(avatar, "Arjun", "अर्जुन")
            self.assertIn("अर्जुन", skills.greeting(avatar))                    # walking up: greets by name
            self.assertIn("नाम क्या है", skills.greeting(avatar, ask_name=True))  # app start: asks again
            self.assertEqual(memory.peek_pending(avatar), "name")
            memory.pending.clear()


if __name__ == "__main__":
    unittest.main()
