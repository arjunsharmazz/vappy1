import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import cv2
import numpy as np


class PiSettingsTests(unittest.TestCase):
    def test_pi5_detected_and_pi_section_applies_only_on_a_pi(self):
        import app.settings as st
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.toml"
            path.write_text('[vision]\nwidth = 640\n[pi.vision]\nwidth = 480\nanalysis_fps = 1.0\n[pi.neural]\nenabled = false\n', encoding="utf-8")
            with patch.object(st, "raspberry_pi_model", return_value=""):
                pc = st.load_settings(path)
            with patch.object(st, "raspberry_pi_model", return_value="pi5"):
                pi = st.load_settings(path)
        self.assertEqual((pc["device"]["resolved_profile"], pc["vision"]["width"], pc["neural"]["enabled"]), ("pc", 640, True))
        self.assertEqual((pi["device"]["resolved_profile"], pi["vision"]["width"], pi["vision"]["analysis_fps"], pi["neural"]["enabled"]),
                         ("pi5", 480, 1.0, False))
        self.assertLessEqual(pi["stt"]["threads"], 3)

    def test_neural_engine_refuses_when_turned_off(self):
        from app.services.neural_avatar.engine_manager import EngineManager
        from app.settings import get_settings
        with patch.dict(get_settings()["neural"], {"enabled": False}):
            with self.assertRaisesRegex(RuntimeError, "turned off"):
                EngineManager().start("a", Path("x.jpg"), {}, Path("."), "ATLAS", "balanced")


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.prepared, self.data = root / "avtars" / "prepared", root / "avatar_data"
        from app.services import avatar_library as lib
        self.lib = lib
        self.patches = [patch.object(lib, "PREPARED", self.prepared), patch.object(lib, "AVATAR_DATA", self.data),
                        patch.object(lib, "ATLASES", self.data / "neural_atlases")]
        for p in self.patches: p.start()
        self.avatar = str(uuid4())
        bundle = self.prepared / "alia"
        bundle.mkdir(parents=True)
        cv2.imwrite(str(bundle / "original.jpg"), np.full((64, 64, 3), 128, np.uint8))
        cv2.imwrite(str(bundle / "atlas.webp"), np.full((32, 32, 4), 200, np.uint8))
        (bundle / "atlas.json").write_text('{"version": 5, "entries": []}', encoding="utf-8")
        (bundle / "avatar.json").write_text(json.dumps({"avatar_id": self.avatar, "face_detected": True, "animation_available": True,
            "prepared_atlas": "a" * 64, "library_name": "Alia", "gender": "female"}), encoding="utf-8")

    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()

    def test_bundle_installs_once_with_ready_poses(self):
        self.assertEqual(self.lib.install_all(), [self.avatar])
        self.assertTrue((self.data / self.avatar / "avatar.json").is_file())
        self.assertTrue((self.data / "neural_atlases" / ("a" * 64 + ".png")).is_file())
        self.assertEqual(self.lib.install_all(), [self.avatar])  # idempotent
        self.assertEqual(self.lib.listing()[0]["name"], "Alia")

    def test_dropped_cache_is_restored_on_use(self):
        self.lib.install_all()
        (self.data / "neural_atlases" / ("a" * 64 + ".png")).unlink()
        record = json.loads((self.data / self.avatar / "avatar.json").read_text(encoding="utf-8"))
        self.assertEqual(self.lib.prepared_atlas(record), "a" * 64)

    def test_prepared_avatar_is_ready_without_the_engine(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.lib.install_all()
        record = json.loads((self.data / self.avatar / "avatar.json").read_text(encoding="utf-8"))
        with patch("app.services.neural_avatar.routes.read_avatar", return_value=(record, None)), \
             patch("app.services.neural_avatar.routes.manager.start", side_effect=AssertionError("engine must not run")):
            job = TestClient(app).post(f"/avatar/{self.avatar}/neural/atlas").json()
        self.assertEqual(job["state"], "READY")
        self.assertTrue(job["atlas_url"].endswith("a" * 64))


if __name__ == "__main__":
    unittest.main()
