import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.settings import current_gender, persona_gender
from app.services import tts_service
from app.brain.style import finish
from test_upload import UploadTests as _UploadTests


class GenderVoiceTests(unittest.TestCase):
    _base_setUp = _UploadTests.setUp
    tearDown = _UploadTests.tearDown
    upload = _UploadTests.upload

    def setUp(self):
        self._base_setUp()

    def test_upload_stores_the_photo_guess(self):
        with patch('app.imaging.classify_gender', return_value=('male', .81)), \
             patch('app.imaging.mediapipe_landmarks', return_value=({}, None)):
            result = self.upload(self.png).json()
        if not result['face_detected']:
            self.skipTest('synthetic image has no face')
        self.assertEqual((result['gender'], result['gender_confidence']), ('male', .81))

    def test_voice_and_hindi_forms_follow_the_avatar(self):
        token = current_gender.set('male')
        try:
            self.assertEqual(persona_gender(), 'male')
            self.assertEqual(tts_service.edge_voice(), 'hi-IN-MadhurNeural')
            self.assertEqual(finish('मैं ठीक हूँ, मैं करता हूँ।'), 'मैं ठीक हूँ, मैं करता हूँ।')
        finally:
            current_gender.reset(token)
        token = current_gender.set('female')
        try:
            self.assertEqual(tts_service.edge_voice(), 'hi-IN-SwaraNeural')
            self.assertEqual(finish('मैं करता हूँ।'), 'मैं करती हूँ।')
        finally:
            current_gender.reset(token)

    def test_person_can_switch_the_voice(self):
        avatar = str(uuid4())
        folder = self.metadata / avatar
        folder.mkdir(parents=True)
        (folder / 'original.jpg').write_bytes(b'x')
        (folder / 'avatar.json').write_text(json.dumps({'avatar_id': avatar, 'face_detected': True, 'gender': 'female'}), encoding='utf-8')
        from app.services.gender import avatar_gender
        self.assertEqual(avatar_gender(avatar, self.metadata), 'female')
        with patch('app.main.read_avatar', return_value=({'avatar_id': avatar, 'face_detected': True, 'gender': 'female'}, folder / 'original.jpg')), \
             patch('app.main.AVATAR_DATA', self.metadata):
            response = self.client.post(f'/avatar/{avatar}/voice', json={'gender': 'male'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(avatar_gender(avatar, self.metadata), 'male')  # the choice wins over the guess
        with patch('app.main.read_avatar', return_value=({}, None)):
            self.assertEqual(self.client.post(f'/avatar/{avatar}/voice', json={'gender': 'robot'}).status_code, 422)


del _UploadTests

if __name__ == '__main__':
    unittest.main()
