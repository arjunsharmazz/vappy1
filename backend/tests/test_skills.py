import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.brain import skills
from app.brain.memory import memory
from app.brain.translit import to_roman


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(memory, "root", Path(self.temp.name)); self.root.start()
        memory.pending.clear(); memory.last_asked.clear()
        self.avatar = str(uuid4())

    def tearDown(self):
        self.root.stop(); self.temp.cleanup()

    def say(self, text):
        result = skills.handle(self.avatar, text)
        return result and result["reply"]

    def test_name_in_english_hinglish_hindi(self):
        self.assertIn("haven't told", self.say("What is my name?"))
        self.assertIn("Arjun", self.say("My name is Arjun"))
        self.assertEqual(self.say("what's my name"), "Your name is Arjun!")
        self.assertIn("Sharma", self.say("mera naam Rohit Sharma hai"))
        self.assertEqual(self.say("mera naam kya hai"), "आपका नाम Rohit Sharma है!")
        self.assertIn("अर्जुन", self.say("मेरा नाम अर्जुन है"))  # Hindi reply says the name in Devanagari
        self.assertEqual(memory.load(self.avatar)["user_name"], "Arjun")
        self.assertEqual(memory.load(self.avatar)["user_name_native"], "अर्जुन")

    def test_pending_name_answer_but_not_phrases(self):
        self.say("what is my name")            # avatar asks for the name
        self.assertIsNone(self.say("theek hai"))  # a known phrase is not a name
        self.say("what is my name")
        self.assertIn("Priya", self.say("Priya"))

    def test_remember_recall_forget(self):
        self.assertIn("remember", self.say("remember that I like masala chai"))
        self.assertIn("याद", self.say("yaad rakhna ki kal doctor ke paas jana hai"))
        recall = self.say("what do you remember")
        self.assertIn("masala chai", recall); self.assertIn("doctor", recall)
        self.say("forget everything")
        self.assertIn("haven't asked", self.say("what do you remember"))

    def test_maths(self):
        self.assertEqual(self.say("what is 12 times 4"), "12 times 4 is 48.")
        self.assertEqual(self.say("5 plus 3 kitna hota hai"), "जवाब है 8।")
        self.assertEqual(self.say("१० भाग ४"), "जवाब है 2.5।")
        self.assertIn("zero", self.say("7 divided by 0").lower())

    def test_news_online_offline(self):
        with patch("app.brain.skills.headlines", return_value=(["A", "B"], 0, True)):
            self.assertIn("1. A. 2. B", self.say("today's news"))
            self.assertIn("ख़बरें", self.say("aaj ki khabar sunao"))
        with patch("app.brain.skills.headlines", return_value=([], None, False)):
            self.assertIn("internet", self.say("news"))

    def test_unrelated_text_is_not_a_skill(self):
        self.assertIsNone(self.say("hello"))
        self.assertIsNone(self.say("Explain how rainbows form"))

    def test_greeting_asks_name_once(self):
        self.assertIn("नाम क्या है", skills.greeting(self.avatar))
        self.assertEqual(skills.maybe_ask_name(self.avatar, ["greeting"], "en"), "")  # asked recently
        memory.set_name(self.avatar, "Arjun")
        self.assertIn("Arjun", skills.greeting(self.avatar))
        self.assertIn("Arjun", skills.facts_for_prompt(self.avatar))

    def test_transliteration(self):
        self.assertEqual(to_roman("अर्जुन"), "Arjun")
        self.assertEqual(to_roman("प्रिया"), "Priyaa")
        self.assertEqual(to_roman("राहुल शर्मा"), "Raahul Sharmaa")

    def test_memory_file_is_json_and_uuid_only(self):
        memory.set_name(self.avatar, "Arjun")
        data = json.loads((Path(self.temp.name) / self.avatar / "memory.json").read_text(encoding="utf-8"))
        self.assertEqual(data["user_name"], "Arjun")
        with self.assertRaises(ValueError):
            memory.load("../../etc")


if __name__ == "__main__":
    unittest.main()


class SpeechUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(memory, "root", Path(self.temp.name)); self.root.start()
        memory.pending.clear(); memory.last_asked.clear()
        self.avatar = str(uuid4())

    def tearDown(self):
        self.root.stop(); self.temp.cleanup()

    def test_cut_off_name_asks_then_accepts(self):
        self.assertEqual(skills.handle(self.avatar, "मेरा नाम")["reply"], "हाँ जी, आपका नाम?")
        self.assertIn("Arjun", skills.handle(self.avatar, "Arjun")["reply"])

    def test_whisper_hotwords_are_names_not_sentences(self):
        with patch.dict(skills.get_settings()["stt"], {"hint_words": "masala chai, Sharma"}):
            self.assertEqual(skills.stt_hotwords(self.avatar), "masala chai, Sharma")
            memory.set_name(self.avatar, "Arjun", "अर्जुन")
            self.assertEqual(skills.stt_hotwords(self.avatar), "masala chai, Sharma, Arjun, अर्जुन")
        # No conversational phrases: Whisper copies them into the transcript on noise.
        self.assertNotIn("kaise", skills.stt_hotwords(self.avatar) or "")

    def test_unsure_recognition_asks_to_repeat(self):
        self.assertIn("again", skills.unclear("what is the weather"))
        with patch.dict(skills.get_settings()["persona"], {"gender": "female"}):
            self.assertIn("सुन नहीं पाई", skills.unclear("mausam kaisa hai"))

    def test_hallucinated_thank_you_is_dropped_but_clear_speech_kept(self):
        from types import SimpleNamespace as NS
        from app.services.speech_recognition.stt_manager import FasterWhisperEngine
        from app.settings import ROOT
        fixture = ROOT / ".tools" / "conversation-fixture.wav"
        if not fixture.is_file():
            self.skipTest("audio fixture missing")
        engine = FasterWhisperEngine()
        # Never write debug recordings from tests into the real avatar_data folder.
        quiet = patch.dict(skills.get_settings()["stt"], {"log_transcripts": False}); quiet.start()
        self.addCleanup(quiet.stop)
        def fake(text, logprob):
            seg = NS(text=text, no_speech_prob=.1, avg_logprob=logprob)
            engine.model = NS(transcribe=lambda *a, **k: ([seg], NS(language="hi")))
        fake(" Thank you.", -.8)
        with self.assertRaises(ValueError):
            engine.transcribe(fixture, "hi")
        fake(" Thank you.", -.2)
        self.assertEqual(engine.transcribe(fixture, "hi")["text"], "Thank you.")
        fake(" mera naam Arjun hai", -1.4)  # pure guesswork is dropped too
        with self.assertRaises(ValueError):
            engine.transcribe(fixture, "hi")


class PendingNameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = patch.object(memory, "root", Path(self.temp.name)); self.root.start()
        memory.pending.clear(); memory.last_asked.clear()
        self.avatar = str(uuid4())

    def tearDown(self):
        self.root.stop(); self.temp.cleanup()

    def test_name_question_survives_small_talk(self):
        skills.greeting(self.avatar)                     # "Aapka naam kya hai?"
        self.assertIsNone(skills.handle(self.avatar, "How are you?"))  # answered by ready replies
        self.assertIn("Arjun", skills.handle(self.avatar, "Arjun.")["reply"])
        self.assertIsNone(memory.peek_pending(self.avatar))


class StyleTests(unittest.TestCase):
    def test_female_verbs_and_hindi_time(self):
        from datetime import datetime
        from app.brain import style
        with patch.dict(style.get_settings()["persona"], {"gender": "female"}):
            self.assertEqual(style.finish("मैं यहीं इंतज़ार करूँगा। मैं बातें कर सकता हूँ।"), "मैं यहीं इंतज़ार करूँगी। मैं बातें कर सकती हूँ।")
            self.assertEqual(style.finish("हो सकता है"), "हो सकता है")  # not about the avatar
            self.assertEqual(style.finish("Main yaad rakhunga"), "Main yaad rakhungi")
        with patch.dict(style.get_settings()["persona"], {"gender": "male"}):
            self.assertEqual(style.finish("मैं करूँगा"), "मैं करूँगा")
        self.assertEqual(style.hindi_time(datetime(2026, 11, 9, 21, 15)), "रात के 9 बजकर 15 मिनट")
        self.assertEqual(style.hindi_time(datetime(2026, 11, 9, 8, 0)), "सुबह के 8 बजे")
        self.assertEqual(style.hindi_date(datetime(2026, 11, 9)), "9 नवंबर 2026")
        self.assertEqual(style.hindi_day(datetime(2026, 11, 9)), "सोमवार")
