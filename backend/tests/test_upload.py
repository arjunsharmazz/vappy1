import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient
from app.main import app


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.uploads = self.root / 'uploads'
        self.metadata = self.root / 'avatar_data'
        self.uploads.mkdir()
        self.metadata.mkdir()
        self.patches = [patch('app.main.UPLOADS', self.uploads), patch('app.main.AVATAR_DATA', self.metadata)]
        for item in self.patches:
            item.start()
        self.client = TestClient(app)
        self.png = cv2.imencode('.png', np.zeros((160, 160, 3), dtype=np.uint8))[1].tobytes()

    def tearDown(self):
        self.client.close()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def upload(self, data, filename='portrait.png'):
        return self.client.post('/avatar/upload', files={'file': (filename, data, 'image/png')})

    def test_health(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok', 'device': 'cpu'})

    def test_no_face_and_saved_metadata(self):
        response = self.upload(self.png)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result['success'])
        self.assertFalse(result['face_detected'])
        self.assertEqual(result['message'], 'No face detected. Please upload a clear front-facing photo.')
        saved = self.uploads / (result['avatar_id'] + '.jpg')
        self.assertIsNotNone(cv2.imread(str(saved)))
        record = json.loads((self.metadata / result['avatar_id'] / 'avatar.json').read_text())
        self.assertEqual(record['avatar_id'], result['avatar_id'])

    def test_positive_response_contract(self):
        # Real detector coverage uses the separate optional portrait smoke check.
        with patch('app.main.process_image', return_value=(self.png, True, {'animation_available': False, 'landmarks': {}})):
            result = self.upload(self.png).json()
        self.assertTrue(result['face_detected'])
        self.assertEqual(result['message'], 'Avatar Ready')

    def test_unique_ids_and_safe_filename(self):
        first = self.upload(self.png, '../../photo.png').json()
        second = self.upload(self.png).json()
        self.assertNotEqual(first['avatar_id'], second['avatar_id'])
        self.assertEqual(len(list(self.uploads.iterdir())), 2)

    def test_invalid_inputs(self):
        for name, data, expected in [('bad.txt', b'text', 415), ('empty.png', b'', 400), ('fake.png', b'not an image', 415), ('broken.png', b'\x89PNG\r\n\x1a\n', 422), ('mismatch.jpg', self.png, 415)]:
            with self.subTest(name=name):
                self.assertEqual(self.upload(data, name).status_code, expected)
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_upload_limit(self):
        with patch('app.main.MAX_UPLOAD_BYTES', 8):
            self.assertEqual(self.upload(self.png).status_code, 413)

    def test_missing_file(self):
        self.assertEqual(self.client.post('/avatar/upload').status_code, 422)

    def test_storage_failure_rolls_back(self):
        with self.assertLogs(level='ERROR'), patch('pathlib.Path.write_text', side_effect=OSError('disk full')):
            self.assertEqual(self.upload(self.png).status_code, 500)
        self.assertEqual(list(self.uploads.iterdir()), [])

    def test_local_cors(self):
        response = self.client.options('/avatar/upload', headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST'})
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:5173')


if __name__ == '__main__':
    unittest.main()
