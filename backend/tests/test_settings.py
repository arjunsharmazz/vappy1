import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app import settings as settings_module
from app.settings import load_settings, public_settings, ROOT


class SettingsTests(unittest.TestCase):
    def write(self, text):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "settings.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_project_config_file_loads(self):
        s = load_settings(ROOT / "config" / "settings.toml")
        self.assertNotEqual(s["source"], "defaults")
        self.assertIn(s["device"]["resolved_profile"], {"pc", "pi4"})
        self.assertGreater(s["stt"]["threads"], 0)
        self.assertTrue(Path(s["llm"]["model_path"]).is_absolute())

    def test_missing_file_uses_defaults(self):
        s = load_settings(Path(tempfile.gettempdir()) / "does-not-exist-living.toml")
        self.assertEqual(s["source"], "defaults")
        self.assertEqual(s["llm"]["port"], 8091)

    def test_invalid_values_fall_back(self):
        path = self.write('[llm]\nport = "abc"\nthreads = -2\n[device]\nprofile = "mars"\n[nope]\nx = 1\n')
        with self.assertLogs("settings", "WARNING"):
            s = load_settings(path)
        self.assertEqual(s["llm"]["port"], 8091)
        self.assertGreater(s["llm"]["threads"], 0)
        self.assertIn(s["device"]["resolved_profile"], {"pc", "pi4"})

    def test_broken_toml_does_not_crash(self):
        path = self.write("[llm\nport = ")
        with self.assertLogs("settings", "ERROR"):
            s = load_settings(path)
        self.assertEqual(s["source"], "defaults")

    def test_pi4_profile_is_lighter(self):
        s = load_settings(self.write('[device]\nprofile = "pi4"\n'))
        self.assertLessEqual(s["llm"]["threads"], 3)
        self.assertEqual(s["llm"]["context"], 2048)

    def test_explicit_threads_are_kept(self):
        s = load_settings(self.write('[device]\nprofile = "pi4"\n[stt]\nthreads = 2\n'))
        self.assertEqual(s["stt"]["threads"], 2)

    def test_legacy_env_override(self):
        with mock.patch.dict(os.environ, {"LIVING_AVATAR_NAME": "Nani"}):
            s = load_settings(self.write(""))
        self.assertEqual(s["persona"]["name"], "Nani")

    def test_public_settings_have_no_paths(self):
        text = repr(public_settings())
        self.assertNotIn(str(ROOT), text)
        self.assertNotIn("model_path", text)


if __name__ == "__main__":
    unittest.main()
