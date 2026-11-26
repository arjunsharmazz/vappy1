import asyncio
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.brain import profile
from app.brain.memory import memory
from app.main import app

patch('app.services.local_ai.online_llm.online_key', return_value='').start()


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = patch.object(memory, 'root', Path(self.tmp.name)); self.root.start()
        self.avatar = str(uuid4())

    def tearDown(self):
        self.root.stop(); self.tmp.cleanup()

    def test_asks_only_every_few_turns_never_every_time(self):
        hints = [profile.plan(self.avatar, rng=lambda: 0) for _ in range(12)]
        asked = [i for i, h in enumerate(hints) if h]
        self.assertGreaterEqual(len(asked), 2)
        self.assertTrue(all(b - a >= 3 for a, b in zip(asked, asked[1:])), asked)
        self.assertIn('their name', hints[asked[0]])  # first thing a friend learns

    def test_merge_dedupes_and_feeds_prompt(self):
        found = {'facts': [{'topic': 'studies_work', 'fact': 'studies B.Tech 2nd year'},
                           {'topic': 'habits', 'fact': 'drinks tea every morning'},
                           {'topic': 'bogus', 'fact': 'ignored'}],
                 'followups': [{'about': 'maths exam', 'date': (date.today() + timedelta(days=2)).isoformat()}]}
        self.assertEqual(profile.merge(self.avatar, found), 3)
        self.assertEqual(profile.merge(self.avatar, found), 0)  # nothing new the second time
        text = profile.facts_text(memory.load(self.avatar))
        self.assertIn('studies B.Tech 2nd year', text)
        self.assertIn('maths exam', text)
        self.assertNotIn('ignored', text)
        self.assertIn('studies_work', profile.known_topics(memory.load(self.avatar)))

    def test_due_followup_is_asked_once(self):
        data = memory.load(self.avatar); data['turns'] = 10; memory._save(self.avatar, data)
        profile.merge(self.avatar, {'followups': [{'about': 'job interview', 'date': date.today().isoformat()}]}, turns=2)
        hint = profile.plan(self.avatar)
        self.assertIn('job interview', hint)
        later = [profile.plan(self.avatar, rng=lambda: 0) for _ in range(10)]
        self.assertFalse(any('job interview' in h for h in later))

    def test_extract_parses_model_json(self):
        reply = {'choices': [{'message': {'content': json.dumps({'facts': [{'topic': 'food', 'fact': 'loves rajma chawal'}], 'followups': []})}}]}

        class Response:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return reply

        class Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): pass
            async def post(self, *a, **k): return Response()

        with patch('app.brain.profile.online_key', return_value='k'), patch('app.brain.profile.httpx.AsyncClient', Client):
            added = asyncio.run(profile.extract(self.avatar, 'मुझे राजमा चावल बहुत पसंद है', 'वाह!', {'models': ['m'], 'base_url': 'x'}))
        self.assertEqual(added, 1)
        self.assertIn('rajma', profile.facts_text(memory.load(self.avatar)))


class CheckinRouteTests(unittest.TestCase):
    def test_quiet_person_gets_a_conversation_starter(self):
        client = TestClient(app)
        body = {'session_id': str(uuid4()), 'turn_id': str(uuid4()), 'text': 'checkin', 'kind': 'observation'}
        with patch('app.services.conversation_routes.valid_avatar'):
            response = client.post(f'/avatar/{uuid4()}/conversation', json=body)
        items = [json.loads(line) for line in response.text.splitlines()]
        self.assertIn('क्या चल रहा है', ''.join(i['text'] for i in items if i['type'] == 'chunk'))
        self.assertEqual(items[-1]['metrics']['intents'], ['checkin'])


if __name__ == '__main__':
    unittest.main()


class LearningRouteTests(unittest.TestCase):
    def test_online_reply_triggers_background_learning(self):
        calls = []
        async def stream(*args, **kwargs):
            yield '[happy] वाह, बढ़िया!'
        async def extract(avatar_id, said, reply, config):
            calls.append((said, reply, config['model']))
        client = TestClient(app)
        body = {'session_id': str(uuid4()), 'turn_id': str(uuid4()), 'text': 'मैं B.Tech में पढ़ता हूँ'}
        with patch('app.services.conversation_routes.valid_avatar'), \
             patch('app.services.conversation_routes.llm.stream', stream), \
             patch('app.services.conversation_routes.llm.online_ready', return_value=True), \
             patch('app.services.conversation_routes.llm.last_source', 'online-ai:test'), \
             patch('app.services.conversation_routes.profile.plan', return_value=''), \
             patch('app.services.conversation_routes.profile.extract', extract):
            response = client.post(f'/avatar/{uuid4()}/conversation', json=body)
        self.assertEqual(json.loads(response.text.splitlines()[-1])['type'], 'done')
        self.assertEqual(calls[0][0], 'मैं B.Tech में पढ़ता हूँ')
