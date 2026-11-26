import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient

from app.brain.canned_replies import CannedReplies, normalize
from app.settings import ROOT
from app.vision.face_tracker import FaceTracker

# Tests must not depend on a real API key in config/.env: behave as the offline frame.
patch('app.services.local_ai.online_llm.online_key', return_value='').start()


class RepliesTests(unittest.TestCase):
    def setUp(self):
        self.r = CannedReplies(ROOT / "config" / "replies.json")

    def intents(self, text):
        m = self.r.match(text)
        return m and m["intents"]

    def test_english_hindi_hinglish(self):
        self.assertEqual(self.intents("Hi!"), ["greeting"])
        self.assertEqual(self.intents("नमस्ते"), ["greeting"])
        self.assertEqual(self.intents("namaste ji"), ["greeting"])
        self.assertEqual(self.intents("What is your name?"), ["name"])
        self.assertEqual(self.intents("tumhara naam kya hai"), ["name"])
        self.assertEqual(self.intents("आपका नाम क्या है?"), ["name"])
        self.assertEqual(self.intents("dhanyawad"), ["thanks"])
        self.assertEqual(self.intents("main thak gayi hoon"), ["tired"])

    def test_two_phrases_are_combined_in_order(self):
        self.assertEqual(self.intents("Hello, how are you?"), ["greeting", "how_are_you"])

    def test_reply_language_follows_input(self):
        self.assertEqual(self.r.match("how are you")["language"], "en")
        self.assertEqual(self.r.match("kaise ho")["language"], "hinglish")
        self.assertEqual(self.r.match("कैसे हो")["language"], "hinglish")

    def test_spelling_variants_and_fuzzy(self):
        self.assertEqual(normalize("Achha!!"), normalize("acha"))
        self.assertEqual(self.intents("kese ho"), ["how_are_you"])
        self.assertEqual(self.intents("मैं ठीक हूं"), ["i_am_fine"])  # anusvara vs chandrabindu

    def test_long_unrelated_question_goes_to_llm(self):
        self.assertIsNone(self.r.match("ok tell me about the history of India please"))
        self.assertIsNone(self.r.match("Explain how rainbows form"))

    def test_hindi_replies_are_devanagari(self):
        reply = self.r.match("kitne baje hain")["reply"]
        self.assertRegex(reply, "[ऀ-ॿ]")
        self.assertIn("बज", reply)
        self.assertNotIn("{", reply)

    def test_placeholders_filled(self):
        reply = self.r.match("what time is it")["reply"]
        self.assertNotIn("{", reply)
        self.assertRegex(reply, r"\d{1,2}:\d{2} (AM|PM)")

    def test_broken_file_keeps_working(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "replies.json"
            path.write_text(json.dumps({"intents": [{"id": "x", "patterns": {"en": ["hello"]},
                                                     "replies": {"en": ["Hi there"]}}]}), encoding="utf-8")
            r = CannedReplies(path)
            self.assertEqual(r.match("hello")["reply"], "Hi there")
            path.write_text("{ broken", encoding="utf-8")
            import os; os.utime(path, (1, 1))
            with self.assertLogs("brain.replies", "ERROR"):
                self.assertEqual(r.match("hello")["reply"], "Hi there")
            self.assertTrue(r.fallback("??"))

    def test_conversation_route_uses_ready_reply_without_llm(self):
        client = TestClient(__import__("app.main", fromlist=["app"]).app)
        body = {"text": "namaste", "session_id": str(uuid4()), "turn_id": str(uuid4())}
        async def must_not_run(*args):
            raise AssertionError("LLM should not be called")
            yield
        with patch("app.services.conversation_routes.valid_avatar"), \
             patch("app.services.conversation_routes.llm.stream", must_not_run):
            response = client.post(f"/avatar/{uuid4()}/conversation", json=body)
        items = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(items[-1]["type"], "done")
        self.assertEqual(items[-1]["metrics"]["reply_source"], "ready-made")
        self.assertTrue(any(i["type"] == "chunk" for i in items))
        client.close()


class FakeDetector:
    name = "fake"
    def __init__(self): self.faces = []
    def detect(self, frame): return self.faces


class TrackerTests(unittest.TestCase):
    def test_presence_hysteresis_and_position(self):
        d = FakeDetector(); t = FaceTracker(d, 320, 240, appear_seconds=.3, leave_seconds=2, smoothing=1)
        frame = np.zeros((240, 320, 3), np.uint8)
        d.faces = [(240, 80, 60, 60, .9), (10, 10, 20, 20, .9)]  # largest face wins
        self.assertFalse(t.update(frame, 0.0)["present"])
        s = t.update(frame, 0.4)
        self.assertTrue(s["present"])
        self.assertAlmostEqual(s["x"], (270 / 320) * 2 - 1, places=3)
        d.faces = []
        self.assertTrue(t.update(frame, 1.5)["present"])   # brief miss: still present
        self.assertFalse(t.update(frame, 2.6)["present"])  # gone for > 2 s: idle

    def test_vision_disabled_stream_is_harmless(self):
        from app.main import app
        client = TestClient(app)
        with patch("app.vision.service.VisionService.enabled", new=False):
            text = client.get("/vision/stream").text
        self.assertIn('"disabled": true', text)
        self.assertEqual(client.get("/vision/status").status_code, 200)
        client.close()


if __name__ == "__main__":
    unittest.main()


class UnclearSpeechRouteTests(unittest.TestCase):
    def test_low_confidence_unknown_speech_asks_to_repeat_without_llm(self):
        from app.main import app
        client = TestClient(app)
        async def must_not_run(*args):
            raise AssertionError("LLM should not answer unsure speech")
            yield
        body = {"text": "blorp something mumble", "session_id": str(uuid4()), "turn_id": str(uuid4()), "stt_confidence": -0.95}
        with patch("app.services.conversation_routes.valid_avatar"), patch("app.services.conversation_routes.llm.stream", must_not_run):
            items = [json.loads(l) for l in client.post(f"/avatar/{uuid4()}/conversation", json=body).text.splitlines()]
        self.assertEqual(items[-1]["metrics"]["intents"], ["unclear"])
        # A known phrase is still answered even when confidence is low.
        body.update(text="namaste", turn_id=str(uuid4()))
        with patch("app.services.conversation_routes.valid_avatar"), patch("app.services.conversation_routes.llm.stream", must_not_run):
            items = [json.loads(l) for l in client.post(f"/avatar/{uuid4()}/conversation", json=body).text.splitlines()]
        self.assertEqual(items[-1]["metrics"]["intents"], ["greeting"])
        client.close()
