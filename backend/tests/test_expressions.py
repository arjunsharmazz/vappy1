import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.vision.expressions import ExpressionReader, hand_gestures, oscillates

patch('app.services.local_ai.online_llm.online_key', return_value='').start()

FACE = (0.4, 0.3, 0.6, 0.6)  # x0, y0, x1, y1


def hand_at(px, py, tip_y=None):
    """21 hand points clustered at (px, py); fingertips optionally higher (tip_y)."""
    points = [(px, py)] * 21
    if tip_y is not None:
        for i in (4, 8, 12, 16, 20):
            points[i] = (px, tip_y)
    return points


def run(reader, seconds, **frame):
    t = getattr(reader, '_t', 0.0)
    result = None
    for _ in range(int(seconds * 4)):
        t += 0.25
        result = reader.update(t, **frame)
    reader._t = t
    return result


class GestureGeometryTests(unittest.TestCase):
    def test_hand_positions_relative_to_face(self):
        self.assertIn('hand_on_head', hand_gestures([hand_at(0.5, 0.33, tip_y=0.25)], FACE))
        self.assertIn('hand_on_chin', hand_gestures([hand_at(0.5, 0.62)], FACE))
        self.assertIn('hand_over_mouth', hand_gestures([hand_at(0.5, 0.53)], FACE))
        self.assertIn('hand_on_cheek', hand_gestures([hand_at(0.6, 0.45)], FACE))
        both = hand_gestures([hand_at(0.47, 0.42), hand_at(0.53, 0.44)], FACE)
        self.assertIn('covering_face', both)
        self.assertEqual(hand_gestures([hand_at(0.9, 0.9)], FACE), set())
        self.assertEqual(hand_gestures([], FACE), set())

    def test_oscillation(self):
        self.assertTrue(oscillates([0, 8, 0, 8, 0, 8], 7))
        self.assertFalse(oscillates([0, 2, 4, 6, 8, 10], 7))
        self.assertFalse(oscillates([0, 1, 0, 1, 0, 1], 7))


class ExpressionReaderTests(unittest.TestCase):
    def test_smile_then_laugh_hard(self):
        r = ExpressionReader()
        self.assertEqual(run(r, 2, blend={'mouthSmileLeft': .7, 'mouthSmileRight': .7})['emotion'], 'smiling')
        hard = {'mouthSmileLeft': .9, 'mouthSmileRight': .9, 'jawOpen': .75, 'eyeSquintLeft': .6, 'eyeSquintRight': .6}
        self.assertEqual(run(r, 3, blend=hard)['emotion'], 'laughing_hard')
        self.assertEqual([e['name'] for e in r.result(r._t)['events']][:1], ['smiling'])

    def test_hand_on_head_reads_as_tension(self):
        r = ExpressionReader()
        result = run(r, 3, blend={'browDownLeft': .4, 'browDownRight': .4}, face_box=FACE,
                     hands=[hand_at(0.5, 0.33, tip_y=0.25)])
        self.assertEqual(result['emotion'], 'tense')
        self.assertIn('hand_on_head', result['gestures'])
        self.assertIn('टेंशन', result['emotion_hi'])
        self.assertIn('tense', r.describe(r._t))
        self.assertIn('hand on head', r.describe(r._t))

    def test_sad_face_with_classifier_and_covered_face_reads_as_crying(self):
        r = ExpressionReader()
        r.set_classifier([0, 0, 0, 0, 0, 0, 0.9, 0.1])
        sad = {'mouthFrownLeft': .5, 'mouthFrownRight': .5, 'browInnerUp': .6}
        self.assertEqual(run(r, 3, blend=sad)['emotion'], 'sad')
        crying = run(r, 3, blend={**sad, 'eyeSquintLeft': .7, 'eyeSquintRight': .7, 'eyeBlinkLeft': .5, 'eyeBlinkRight': .5},
                     face_box=FACE, hands=[hand_at(0.47, 0.42), hand_at(0.53, 0.44)])
        self.assertEqual(crying['emotion'], 'crying')

    def test_brief_spike_does_not_flip_label(self):
        r = ExpressionReader()
        run(r, 2, blend={})
        r.update(r._t + 0.25, blend={'mouthSmileLeft': 1, 'mouthSmileRight': 1})
        self.assertEqual(r.dominant, 'neutral')

    def test_talking_is_not_laughing_and_nod_is_seen(self):
        r = ExpressionReader()
        t = 0.0
        for i in range(24):
            t += 0.25
            result = r.update(t, blend={'jawOpen': 0.35 if i % 2 else 0.05}, pose=(0, 10 if i % 2 else -2, 0))
        self.assertIn('talking', result['gestures'])
        self.assertIn('nodding', result['gestures'])
        self.assertNotIn(result['emotion'], ('laughing', 'laughing_hard', 'yawning', 'surprised'))

    def test_describe_is_empty_when_stale(self):
        r = ExpressionReader()
        run(r, 1, blend={})
        self.assertEqual(r.describe(r._t + 10), '')


class ObservationRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.body = {'session_id': str(uuid4()), 'turn_id': str(uuid4()), 'text': 'tense', 'kind': 'observation'}

    def post(self):
        with patch('app.services.conversation_routes.valid_avatar'):
            response = self.client.post(f'/avatar/{uuid4()}/conversation', json=self.body)
        return [json.loads(line) for line in response.text.splitlines()]

    def test_offline_uses_a_ready_caring_line(self):
        items = self.post()
        self.assertIn('टेंशन', ''.join(i['text'] for i in items if i['type'] == 'chunk'))
        self.assertEqual(items[-1]['metrics']['intents'], ['noticed'])

    def test_online_brain_is_told_what_it_noticed(self):
        seen = []
        async def stream(*args, **kwargs):
            seen.append(kwargs['online_messages'])
            yield '[caring] सब ठीक है? आप थोड़े परेशान लग रहे हो।'
        with patch('app.services.conversation_routes.llm.stream', stream), \
             patch('app.services.conversation_routes.llm.online_ready', return_value=True), \
             patch('app.services.conversation_routes.vision.describe_person', return_value='look tense (hand on head/forehead)'):
            items = self.post()
        self.assertIn('No words were spoken', seen[0][-1]['content'])
        self.assertIn('hand on head', seen[0][-1]['content'])
        self.assertEqual([i['name'] for i in items if i['type'] == 'emotion'], ['caring'])

    def test_speech_turn_includes_what_is_seen(self):
        seen = []
        async def stream(*args, **kwargs):
            seen.append(kwargs['online_messages'][0]['content'])
            yield 'ठीक है।'
        with patch('app.services.conversation_routes.llm.stream', stream), \
             patch('app.services.conversation_routes.llm.online_ready', return_value=True), \
             patch('app.services.conversation_routes.vision.describe_person', return_value='look laughing'):
            with patch('app.services.conversation_routes.valid_avatar'):
                self.client.post(f'/avatar/{uuid4()}/conversation',
                                 json={**self.body, 'kind': 'speech', 'text': 'कैसी हो?'})
        self.assertIn('You can see them (live): they look laughing', seen[0])


if __name__ == '__main__':
    unittest.main()


def synthetic_hand(open_fingers, thumb=False, x=0.5, y=0.8, s=0.1):
    """Upright hand: wrist at bottom, fingers pointing up; closed fingers curl back to the palm."""
    pts = [(x, y)] * 21
    pts[0] = (x, y)
    bases = {5: -0.3, 9: -0.1, 13: 0.1, 17: 0.3}  # knuckle x-offsets (index..pinky)
    for finger, (mcp, pip, dip, tip) in enumerate(((5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20))):
        bx = x + bases[mcp] * s
        pts[mcp] = (bx, y - 0.9 * s)
        pts[pip] = (bx, y - 1.4 * s)
        if finger < open_fingers:
            pts[dip], pts[tip] = (bx, y - 1.8 * s), (bx, y - 2.2 * s)
        else:
            pts[dip], pts[tip] = (bx, y - 1.1 * s), (bx, y - 0.95 * s)
    pts[1], pts[2] = (x - 0.25 * s, y - 0.2 * s), (x - 0.45 * s, y - 0.45 * s)
    if thumb:
        pts[3], pts[4] = (x - 0.7 * s, y - 0.65 * s), (x - 1.0 * s, y - 0.85 * s)
    else:
        pts[3], pts[4] = (x - 0.45 * s, y - 0.7 * s), (x - 0.2 * s, y - 0.85 * s)
    return pts


class FingerCountTests(unittest.TestCase):
    def test_counts_each_shape(self):
        from app.vision.expressions import count_fingers
        for n in range(5):
            self.assertEqual(count_fingers(synthetic_hand(n)), n, n)
        self.assertEqual(count_fingers(synthetic_hand(4, thumb=True)), 5)
        self.assertEqual(count_fingers(synthetic_hand(0, thumb=True)), 1)

    def test_stable_total_over_two_hands_and_reset(self):
        r = ExpressionReader()
        result = run(r, 0.5, hands=[synthetic_hand(2), synthetic_hand(4, thumb=True, x=0.2)])
        self.assertIsNone(result['fingers']['shown'])  # not yet stable
        result = run(r, 1.0, hands=[synthetic_hand(2), synthetic_hand(4, thumb=True, x=0.2)])
        self.assertEqual(result['fingers']['shown'], 7)
        self.assertEqual(result['fingers']['per_hand'], [2, 5])
        self.assertIn('showing_fingers', result['gestures'])
        self.assertEqual(result['events'][-1]['label'], 'सात उंगलियाँ')
        self.assertIn('holding up 7 fingers', r.describe(r._t))
        self.assertIsNone(run(r, 0.5, hands=[])['fingers'])
        thumbs = run(r, 1.5, hands=[synthetic_hand(0, thumb=True)], hand_names=['Thumb_Up'])
        self.assertIsNone(thumbs['fingers'])  # thumbs up is a gesture, not "one finger"


class FingerRouteTests(unittest.TestCase):
    def test_finger_count_gets_an_instant_exact_answer_without_ai(self):
        async def must_not_run(*args, **kwargs):
            raise AssertionError('no AI for counting')
            yield
        client = TestClient(app)
        body = {'session_id': str(uuid4()), 'turn_id': str(uuid4()), 'text': 'fingers:3', 'kind': 'observation'}
        with patch('app.services.conversation_routes.valid_avatar'), \
             patch('app.services.conversation_routes.llm.stream', must_not_run), \
             patch('app.services.conversation_routes.llm.online_ready', return_value=True):
            response = client.post(f'/avatar/{uuid4()}/conversation', json=body)
        items = [json.loads(line) for line in response.text.splitlines()]
        spoken = ''.join(i['text'] for i in items if i['type'] == 'chunk')
        self.assertIn('तीन', spoken)
        self.assertNotIn('रहा हूँ', spoken)  # female persona: feminine verb
        self.assertEqual(items[-1]['metrics']['intents'], ['fingers'])

    def test_laugh_observation_asks_ai_to_laugh_along(self):
        seen = []
        async def stream(*args, **kwargs):
            seen.append(kwargs['online_messages'][-1]['content'])
            yield '[laugh] हाहा, क्या हुआ?'
        client = TestClient(app)
        body = {'session_id': str(uuid4()), 'turn_id': str(uuid4()), 'text': 'laughing', 'kind': 'observation'}
        with patch('app.services.conversation_routes.valid_avatar'), \
             patch('app.services.conversation_routes.llm.stream', stream), \
             patch('app.services.conversation_routes.llm.online_ready', return_value=True), \
             patch('app.services.conversation_routes.vision.describe_person', return_value=''):
            response = client.post(f'/avatar/{uuid4()}/conversation', json=body)
        self.assertIn('Laugh along', seen[0])
        self.assertIn('"emotion", "name": "laugh"', response.text.replace("'", '"'))
