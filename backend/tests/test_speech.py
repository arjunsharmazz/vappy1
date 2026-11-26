import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4
import wave

import numpy as np
from fastapi import HTTPException

from app.services.tts_service import generate_speech, validate_wav, _SYNTHESIS_LOCK
from test_upload import UploadTests as _UploadTests

# The online (Microsoft) voice needs the network; the offline engines are tested here, and the
# online path has its own mocked tests in OnlineVoiceTests.
patch('app.services.tts_service._edge_usable', return_value=False).start()


def make_wav(path, silent=False):
    samples = np.zeros(2205, dtype="<i2") if silent else (np.sin(np.arange(2205) * .12) * 12000).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(22050)
        wav.writeframes(samples.tobytes())


class SpeechTests(unittest.TestCase):
    # These cover the Windows SAPI path and its fallback; Piper has its own tests below.
    _base_setUp = _UploadTests.setUp
    _base_tearDown = _UploadTests.tearDown

    def setUp(self):
        self._base_setUp()
        self.sapi = patch('app.services.tts_service._provider', return_value='sapi'); self.sapi.start()

    def tearDown(self):
        self.sapi.stop(); self._base_tearDown()

    upload = _UploadTests.upload

    def avatar(self):
        record = self.upload(self.png).json()
        location = self.metadata / record['avatar_id'] / 'avatar.json'
        record['face_detected'] = True
        location.write_text(json.dumps(record))
        return record['avatar_id']

    def test_text_validation(self):
        avatar_id = self.avatar()
        for text in ['', '   ', 'x' * 501, '!!!', '\u0000Hello', 123, None]:
            self.assertEqual(self.client.post(f'/avatar/{avatar_id}/speak', json={'text': text}).status_code, 422)
        self.assertEqual(self.client.post(f'/avatar/{avatar_id}/speak', json={}).status_code, 422)

    def test_no_face_rejected(self):
        avatar_id = self.upload(self.png).json()['avatar_id']
        self.assertEqual(self.client.post(f'/avatar/{avatar_id}/speak', json={'text':'Hello'}).status_code, 409)

    def test_speech_routes_and_real_wav_validation(self):
        avatar_id = self.avatar()
        with patch('app.services.tts_service._run_pyttsx3', side_effect=lambda text, path: make_wav(path)):
            response = self.client.post(f'/avatar/{avatar_id}/speak', json={'text':'Hello'})
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertGreater(result['rms'], .01)
        audio = self.client.get(result['audio_url'])
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.headers['content-type'], 'audio/wav')
        self.assertTrue(audio.content.startswith(b'RIFF'))
        self.assertEqual(len(list((self.metadata / avatar_id / 'audio').glob('*.pending.wav'))), 0)

    def test_local_fallback_after_invalid_primary(self):
        avatar_id = self.avatar()
        with patch('app.services.tts_service._run_pyttsx3', side_effect=lambda text, path: path.write_bytes(b'')), patch('app.services.tts_service._run_windows_fallback', side_effect=lambda text, path: make_wav(path)), self.assertLogs(level='WARNING'):
            result = generate_speech(avatar_id, 'Hello', self.metadata)
        self.assertEqual(result['tts_engine'], 'windows-system-speech')

    def test_silent_or_failed_engines_never_report_success(self):
        avatar_id = self.avatar()
        with patch('app.services.tts_service._run_pyttsx3', side_effect=lambda text, path: make_wav(path, True)), patch('app.services.tts_service._run_windows_fallback', side_effect=lambda text, path: make_wav(path, True)), self.assertLogs(level='WARNING'):
            response = self.client.post(f'/avatar/{avatar_id}/speak', json={'text':'Hello'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(list((self.metadata / avatar_id / 'audio').iterdir()), [])

    def test_timeout_is_bounded_and_unlocks(self):
        with patch('app.services.tts_service._run_pyttsx3', side_effect=subprocess.TimeoutExpired('worker',45)), patch('app.services.tts_service._run_windows_fallback', side_effect=subprocess.TimeoutExpired('worker',45)), self.assertLogs(level='WARNING'):
            with self.assertRaises(HTTPException) as error:
                generate_speech(str(uuid4()), 'Hello', self.metadata)
        self.assertEqual(error.exception.status_code, 503)
        self.assertTrue(_SYNTHESIS_LOCK.acquire(False))
        _SYNTHESIS_LOCK.release()

    def test_busy_engine(self):
        _SYNTHESIS_LOCK.acquire()
        try:
          with patch('app.services.tts_service.LOCK_WAIT_SECONDS', 0):
            with self.assertRaises(HTTPException) as error:
                generate_speech(str(uuid4()), 'Busy check', self.metadata)
            self.assertEqual(error.exception.status_code, 429)
        finally:
            _SYNTHESIS_LOCK.release()

    def test_missing_and_invalid_audio_ids(self):
        avatar_id = self.avatar()
        self.assertEqual(self.client.get(f'/avatar/{avatar_id}/audio/not-a-uuid').status_code, 400)
        self.assertEqual(self.client.get(f'/avatar/{avatar_id}/audio/{uuid4()}').status_code, 404)
        self.assertEqual(self.client.post('/avatar/bad-id/speak', json={'text':'Hello'}).status_code, 400)

    def test_corrupt_audio_rejected(self):
        avatar_id = self.avatar()
        speech_id = str(uuid4())
        folder = self.metadata / avatar_id / 'audio'
        folder.mkdir()
        (folder / (speech_id + '.wav')).write_bytes(b'invalid')
        self.assertEqual(self.client.get(f'/avatar/{avatar_id}/audio/{speech_id}').status_code, 422)

    def test_wav_validation_rejects_truncation(self):
        target = self.root / 'truncated.wav'
        make_wav(target)
        target.write_bytes(target.read_bytes()[:-100])
        with self.assertRaises(ValueError):
            validate_wav(target)



class PiperTests(unittest.TestCase):
    _base_setUp = _UploadTests.setUp
    tearDown = _UploadTests.tearDown

    def setUp(self):
        from app.services.tts_service import piper_model
        if piper_model() is None:
            self.skipTest('Piper voice not installed')
        self._base_setUp()

    def test_hindi_voice_speaks_devanagari_and_reuses_cache(self):
        avatar = str(uuid4())
        first = generate_speech(avatar, 'नमस्ते! आपको देखकर बहुत अच्छा लगा।', self.metadata)
        self.assertTrue(first['tts_engine'].startswith('piper:'))
        self.assertGreater(first['duration_seconds'], 1)
        again = generate_speech(avatar, 'नमस्ते! आपको देखकर बहुत अच्छा लगा।', self.metadata)
        self.assertEqual(again['tts_engine'], 'cache')
        self.assertEqual(again['speech_id'], first['speech_id'])

    def test_piper_failure_falls_back_to_windows(self):
        import sys
        if sys.platform != 'win32':
            self.skipTest('Windows fallback only')
        with patch('app.services.tts_service._run_piper', side_effect=RuntimeError('broken voice')),              patch('app.services.tts_service._run_pyttsx3', side_effect=lambda text, path: make_wav(path)),              self.assertLogs(level='ERROR'):
            result = generate_speech(str(uuid4()), 'Fallback check', self.metadata)
        self.assertEqual(result['tts_engine'], 'pyttsx3-sapi5')


class OnlineVoiceTests(unittest.TestCase):
    _base_setUp = _UploadTests.setUp
    tearDown = _UploadTests.tearDown

    def setUp(self):
        self._base_setUp()
        from app.services import tts_service
        self.tts = tts_service
        tts_service._EDGE["failed_at"] = 0.0
        self.usable = patch.object(tts_service, '_edge_usable', side_effect=lambda: tts_service.time.monotonic()
                                   - tts_service._EDGE["failed_at"] >= tts_service.EDGE_RETRY_SECONDS)
        self.usable.start()
        self.addCleanup(self.usable.stop)

    def test_online_voice_is_used_and_cached(self):
        avatar = str(uuid4())
        with patch.object(self.tts, '_run_edge', side_effect=lambda text, path: make_wav(path)) as run:
            first = generate_speech(avatar, 'नमस्ते, कैसे हो?', self.metadata)
            again = generate_speech(avatar, 'नमस्ते, कैसे हो?', self.metadata)
        self.assertTrue(first['tts_engine'].startswith('edge:hi-IN-'))
        self.assertEqual(again['tts_engine'], 'cache')
        self.assertEqual(run.call_count, 1)
        self.assertEqual(list((self.metadata / avatar / 'audio').glob('*.pending.wav')), [])

    def test_offline_falls_back_and_pauses_online_voice(self):
        avatar = str(uuid4())
        with patch.object(self.tts, '_run_edge', side_effect=OSError('no internet')) as run,              patch.object(self.tts, '_provider', return_value='sapi'),              patch.object(self.tts, '_run_pyttsx3', side_effect=lambda text, path: make_wav(path)),              self.assertLogs(level='WARNING'):
            first = generate_speech(avatar, 'Offline one', self.metadata)
            second = generate_speech(avatar, 'Offline two', self.metadata)
        self.assertEqual(first['tts_engine'], 'pyttsx3-sapi5')
        self.assertEqual(second['tts_engine'], 'pyttsx3-sapi5')
        self.assertEqual(run.call_count, 1)  # second sentence does not wait for the network again


del _UploadTests

if __name__ == '__main__':
    unittest.main()

