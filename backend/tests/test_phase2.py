import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.imaging import process_image
from app.services.face_landmarks import WARNING
from test_upload import UploadTests as _UploadTests


class AvatarRetrievalTests(unittest.TestCase):
    setUp = _UploadTests.setUp
    tearDown = _UploadTests.tearDown
    upload = _UploadTests.upload
    def test_new_storage_and_routes(self):
        result = self.upload(self.png).json()
        avatar_id = result['avatar_id']
        self.assertTrue((self.metadata / avatar_id / 'original.jpg').is_file())
        response = self.client.get('/avatar/' + avatar_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'no_face')
        image = self.client.get(result['image_url'])
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers['content-type'], 'image/jpeg')

    def test_invalid_and_missing_ids(self):
        for value in ['bad-id', 'not-a-uuid.jpg']:
            self.assertEqual(self.client.get('/avatar/' + value + '/image').status_code, 400)
        self.assertEqual(self.client.get('/avatar/' + str(uuid4())).status_code, 404)

    def test_missing_image(self):
        result = self.upload(self.png).json()
        (self.metadata / result['avatar_id'] / 'original.jpg').unlink()
        for endpoint in ['/avatar/' + result['avatar_id'], result['image_url']]:
            self.assertEqual(self.client.get(endpoint).status_code, 404)

    def test_corrupt_image(self):
        result = self.upload(self.png).json()
        (self.metadata / result['avatar_id'] / 'original.jpg').write_bytes(b'bad image')
        self.assertEqual(self.client.get(result['image_url']).status_code, 422)

    def test_corrupt_metadata(self):
        result = self.upload(self.png).json()
        (self.metadata / result['avatar_id'] / 'avatar.json').write_text('{broken')
        self.assertEqual(self.client.get('/avatar/' + result['avatar_id']).status_code, 422)

    def test_phase1_record_compatibility(self):
        avatar_id = str(uuid4())
        (self.uploads / (avatar_id + '.jpg')).write_bytes(self.png)
        (self.metadata / (avatar_id + '.json')).write_text(json.dumps({
            'avatar_id': avatar_id, 'face_detected': True, 'message': 'Avatar Ready'}))
        response = self.client.get('/avatar/' + avatar_id)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['animation_available'])
        self.assertEqual(response.json()['warning'], WARNING)
        self.assertEqual(self.client.get(response.json()['image_url']).status_code, 200)

    def test_landmark_failure_preserves_valid_face(self):
        detector = unittest.mock.Mock()
        detector.empty.return_value = False
        detector.detectMultiScale.return_value = [(20, 20, 100, 100)]
        with patch('app.imaging.cv2.CascadeClassifier', return_value=detector), patch('app.imaging.mediapipe_landmarks', return_value=({}, None)),              patch('app.imaging.extract_landmarks', side_effect=RuntimeError('failed')), self.assertLogs(level='ERROR'):
            result = self.upload(self.png).json()
        # Eye detection failing no longer switches animation off: face proportions are used.
        self.assertTrue(result['face_detected'])
        self.assertTrue(result['animation_available'])
        self.assertEqual(result['landmark_method'], 'face_proportions')
        self.assertIsNone(result['warning'])
        self.assertEqual(self.client.get(result['image_url']).status_code, 200)

    def test_absent_eyes_preserve_valid_face(self):
        detector = unittest.mock.Mock()
        detector.empty.return_value = False
        detector.detectMultiScale.return_value = [(20, 20, 100, 100)]
        with patch('app.imaging.cv2.CascadeClassifier', return_value=detector), patch('app.imaging.mediapipe_landmarks', return_value=({}, None)),              patch('app.imaging.extract_landmarks', return_value={}):
            result = self.upload(self.png).json()
        self.assertTrue(result['animation_available'])
        self.assertEqual(result['landmark_method'], 'face_proportions')
        self.assertIn('left_eye', result['landmarks'])

    def test_mediapipe_landmarks_used_when_available(self):
        precise = {'left_eye': {'x': 40, 'y': 50, 'width': 12, 'height': 6}, 'right_eye': {'x': 80, 'y': 50, 'width': 12, 'height': 6},
                   'mouth': {'x': 60, 'y': 95, 'width': 30, 'height': 10}, 'face_center': {'x': 60, 'y': 70}}
        with patch('app.imaging.mediapipe_landmarks', return_value=(precise, (20, 20, 80, 80))):
            result = self.upload(self.png).json()
        self.assertTrue(result['face_detected'])
        self.assertTrue(result['animation_available'])
        self.assertEqual(result['landmark_method'], 'mediapipe_face_mesh')
        self.assertIsNone(result['warning'])

    def test_coordinates_scale_to_saved_image(self):
        import cv2
        import numpy as np
        png = cv2.imencode('.png', np.zeros((2000, 2000, 3), dtype=np.uint8))[1].tobytes()
        detector = unittest.mock.Mock()
        detector.empty.return_value = False
        detector.detectMultiScale.return_value = [(100, 100, 200, 200)]
        with patch('app.imaging.cv2.CascadeClassifier', return_value=detector), patch('app.imaging.extract_landmarks', return_value={'left_eye': {'x': 150., 'y': 150.}}):
            _, _, details = process_image(png, '.png')
        self.assertEqual(details['image_width'], 1600)
        self.assertEqual(details['face_box']['x'], 200)
        self.assertEqual(details['landmarks']['left_eye']['x'], 300)


del _UploadTests

if __name__ == '__main__':
    unittest.main()
