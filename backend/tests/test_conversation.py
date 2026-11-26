import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient
from app.main import app
from app.services.local_ai.conversation_manager import ConversationManager
from app.services.local_ai.prompt_builder import build_prompt
from app.services.conversation_routes import take_chunk
from app.services.neural_avatar.blending import prepare_blend_mask, composite

# Tests must not depend on a real API key in config/.env (tests that need one patch it in).
patch('app.services.local_ai.online_llm.online_key', return_value='').start()


class MemoryTests(unittest.TestCase):
    def test_memory_clear_isolation_and_cancel(self):
        m = ConversationManager(); key = ('avatar', 'session')
        history, epoch, cancel = m.begin(key, '1')
        self.assertEqual(history, [])
        m.finish(key, '1', epoch, 'My name is Arjun.', 'Hello Arjun.')
        history, epoch, cancel = m.begin(key, '2')
        self.assertIn('Arjun', history[0]['content'])
        m.clear(key); m.finish(key, '2', epoch, 'Question', 'Stale answer')
        history, epoch, cancel = m.begin(key, '3')
        self.assertEqual(history, [])
        m.cancel(key, '3'); self.assertTrue(cancel.is_set())
        m.finish(key, '3', epoch, 'Question', 'Cancelled answer')
        self.assertEqual(m.begin(('avatar', 'different'), '4')[0], [])

    def test_memory_bounded_and_busy(self):
        m = ConversationManager(); key = ('a', 's')
        for i in range(30):
            _, epoch, _ = m.begin(key, str(i))
            with self.assertRaises(RuntimeError): m.begin(key, 'concurrent')
            m.finish(key, str(i), epoch, 'user' * 100, 'answer' * 100)
        history, _, _ = m.begin(key, 'last')
        self.assertLessEqual(len(history), 16)
        self.assertLessEqual(sum(len(v['content']) for v in history), 6000)

    def test_multilingual_prompt_does_not_translate(self):
        text = 'कल weather कैसा रहेगा?'
        prompt = build_prompt([], text)
        self.assertEqual(prompt[-1]['content'], text)
        self.assertIn('Hindi', prompt[0]['content'])

    def test_chunking_sentence_hindi_and_bounded(self):
        self.assertEqual(take_chunk('Hello. How are you?'), ('Hello.', 'How are you?'))
        self.assertEqual(take_chunk('नमस्ते। कैसे हैं?')[0], 'नमस्ते।')
        self.assertEqual(take_chunk('unfinished')[0], None)
        self.assertEqual(take_chunk('unfinished', True)[0], 'unfinished')
        self.assertLessEqual(len(take_chunk('word ' * 100)[0]), 220)
        self.assertLessEqual(len(take_chunk('word ' * 100 + '.')[0]), 220)

    def test_blending_preserves_background_and_upper_face(self):
        mask = np.zeros((100, 100), np.float32); mask[10:90, 10:90] = 1
        box = {'x': 10, 'y': 10, 'width': 80, 'height': 80}
        soft = prepare_blend_mask(mask, box, lower_face=True)
        source = np.full((100, 100, 3), 100, np.uint8)
        output = composite(source, np.full_like(source, 150), soft)
        np.testing.assert_array_equal(output[:40], source[:40])
        np.testing.assert_array_equal(output[mask == 0], source[mask == 0])
        self.assertGreater(output[70, 50, 0], 100)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.avatar = str(uuid4())
        self.valid = patch('app.services.conversation_routes.valid_avatar')
        self.valid.start()
        # Not a ready-made phrase, so these tests exercise the LLM path.
        self.body = {'text': 'Explain how rainbows form', 'session_id': str(uuid4()), 'turn_id': str(uuid4())}

    def tearDown(self):
        self.valid.stop(); self.client.close()

    def test_temp_recording_removed_success_and_failure(self):
        paths = []
        def transcribe(path, language, **kwargs):
            paths.append(path)
            self.assertTrue(path.is_file())
            return {'text': 'hello', 'stt_seconds': .1}
        with patch('app.services.conversation_routes.stt.transcribe', side_effect=transcribe):
            response = self.client.post(f'/avatar/{self.avatar}/listen', files={'file': ('mic.webm', b'example')})
            self.assertEqual(response.status_code, 200)
        self.assertFalse(paths[0].exists())
        def fail(path, language, **kwargs):
            paths.append(path); raise ValueError('No speech detected.')
        with patch('app.services.conversation_routes.stt.transcribe', side_effect=fail):
            response = self.client.post(f'/avatar/{self.avatar}/listen', files={'file': ('mic.webm', b'example')})
            self.assertEqual(response.status_code, 422)
        self.assertFalse(paths[-1].exists())

    def test_bad_audio_and_upload_limit(self):
        response = self.client.post(f'/avatar/{self.avatar}/listen', files={'file': ('bad', b'not audio')})
        self.assertEqual(response.status_code, 422)
        response = self.client.post(f'/avatar/{self.avatar}/listen', files={'file': ('huge', b'x' * (8 * 1024 * 1024 + 1))})
        self.assertEqual(response.status_code, 413)

    def test_validation(self):
        for update in [{'text': ' '}, {'text': 'x' * 501}, {'session_id': '../escape'}, {'response_length': 'huge'}]:
            response = self.client.post(f'/avatar/{self.avatar}/conversation', json={**self.body, **update})
            self.assertEqual(response.status_code, 422)

    def test_stream_and_llm_failure_leave_avatar_usable(self):
        async def stream(*args, **kwargs):
            for text in ['Hello', '. ', 'Welcome.']:
                yield text
        with patch('app.services.conversation_routes.llm.stream', stream):
            response = self.client.post(f'/avatar/{self.avatar}/conversation', json=self.body)
        items = [json.loads(s) for s in response.text.splitlines()]
        self.assertEqual(''.join(s['text'] for s in items if s['type'] == 'token'), 'Hello. Welcome.')
        self.assertEqual(items[-1]['type'], 'done')
        async def fail(*args, **kwargs):
            raise RuntimeError('Local AI unavailable.')
            yield
        with patch('app.services.conversation_routes.llm.stream', fail):
            response = self.client.post(f'/avatar/{self.avatar}/conversation', json=self.body)
        self.assertIn('Local AI unavailable.', response.text)
        self.assertEqual(self.client.get('/health').status_code, 200)

    def test_emotion_tag_becomes_expression_and_is_not_spoken(self):
        async def stream(*args, **kwargs):
            for text in ['[ha', 'ppy] अरे ', 'वाह! **बहुत** अच्छा 😊', '। आप कैसे हैं?']:
                yield text
        with patch('app.services.conversation_routes.llm.stream', stream), \
             patch('app.services.conversation_routes.llm.online_ready', return_value=True):
            response = self.client.post(f'/avatar/{self.avatar}/conversation', json={**self.body, 'text': 'मेरा प्रमोशन हो गया'})
        items = [json.loads(s) for s in response.text.splitlines()]
        self.assertEqual([i['name'] for i in items if i['type'] == 'emotion'], ['happy'])
        spoken = [i['text'] for i in items if i['type'] == 'chunk']
        self.assertEqual(spoken, ['अरे वाह!', 'बहुत अच्छा।', 'आप कैसे हैं?'])
        self.assertNotIn('[', ''.join(i['text'] for i in items if i['type'] == 'token'))
        self.assertEqual(items[-1]['metrics']['emotion'], 'happy')

    def test_online_brain_skips_ready_made_replies(self):
        calls = []
        async def stream(*args, **kwargs):
            calls.append(kwargs.get('online_messages'))
            yield '[calm] नमस्ते, बताइए क्या हाल है?'
        with patch('app.services.conversation_routes.llm.stream', stream), \
             patch('app.services.conversation_routes.llm.online_ready', return_value=True):
            response = self.client.post(f'/avatar/{self.avatar}/conversation', json={**self.body, 'text': 'hello'})
        self.assertEqual(len(calls), 1)
        self.assertIn('Reply to exactly what they just said', calls[0][0]['content'])
        self.assertEqual(calls[0][-1]['content'], 'hello')
        self.assertEqual(json.loads(response.text.splitlines()[-1])['type'], 'done')


class UnsureSpeechTests(unittest.TestCase):
    """Whisper gives clear Hindi about -0.9 to -1.3; the online brain must still answer it."""
    def setUp(self):
        self.client = TestClient(app)
        self.body = {'session_id': str(uuid4()), 'turn_id': str(uuid4()), 'text': 'Abhi Ka Samay Bhatau',
                     'stt_confidence': -1.1}

    def test_online_brain_answers_misheard_hindi_with_a_hint(self):
        seen = []
        async def stream(*args, **kwargs):
            seen.append(kwargs['online_messages'][0]['content'])
            yield '[calm] अभी रात के डेढ़ बजे हैं।'
        with patch('app.services.conversation_routes.valid_avatar'),              patch('app.services.conversation_routes.llm.stream', stream),              patch('app.services.conversation_routes.llm.online_ready', return_value=True):
            response = self.client.post(f'/avatar/{uuid4()}/conversation', json=self.body)
        self.assertEqual(len(seen), 1)
        self.assertIn('Speech recognition was unsure', seen[0])
        self.assertNotIn('unclear', response.text)

    def test_really_poor_recognition_still_asks_to_repeat(self):
        async def must_not_run(*args, **kwargs):
            raise AssertionError('LLM must not run')
            yield
        with patch('app.services.conversation_routes.valid_avatar'),              patch('app.services.conversation_routes.llm.stream', must_not_run),              patch('app.services.conversation_routes.llm.online_ready', return_value=True):
            response = self.client.post(f'/avatar/{uuid4()}/conversation', json={**self.body, 'stt_confidence': -2.5})
        self.assertIn('unclear', response.text)


class OnlineEngineTests(unittest.TestCase):
    def test_streams_openai_compatible_sse_and_retries_without_thinking(self):
        import httpx
        from app.services.local_ai import online_llm
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            assert request.headers['authorization'] == 'Bearer test-key'
            if 'reasoning_effort' in body:
                return httpx.Response(400, json={'error': 'thinking not supported'})
            lines = [{'choices': [{'delta': {'content': '[happy] '}}]}, {'choices': [{'delta': {}}]},
                     {'choices': [{'delta': {'content': 'नमस्ते!'}}]}]
            sse = ''.join(f'data: {json.dumps(l, ensure_ascii=False)}\n\n' for l in lines) + 'data: [DONE]\n\n'
            return httpx.Response(200, content=sse.encode(), headers={'content-type': 'text/event-stream'})

        real = httpx.AsyncClient
        engine = online_llm.OnlineEngine()
        async def run():
            return [t async for t in engine.stream([{'role': 'user', 'content': 'hi'}])]
        from app.settings import get_settings
        with patch.object(online_llm, 'online_key', return_value='test-key'), \
             patch.dict(get_settings()['online_ai'], {'thinking': 'low'}), \
             patch.object(online_llm.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            self.assertTrue(engine.available())
            self.assertEqual(asyncio.run(run()), ['[happy] ', 'नमस्ते!'])
        self.assertEqual(bodies[0]['reasoning_effort'], 'low')
        self.assertNotIn('reasoning_effort', bodies[1])
        self.assertEqual(bodies[1]['model'], 'gemini-3.5-flash-lite')

    def test_busy_model_falls_through_to_next_model(self):
        import httpx
        from app.services.local_ai import online_llm
        models = []

        def handler(request):
            models.append(json.loads(request.content)['model'])
            if len(models) == 1:
                return httpx.Response(503, json={'error': 'high demand'})
            sse = 'data: ' + json.dumps({'choices': [{'delta': {'content': 'ok'}}]}) + '\n\ndata: [DONE]\n\n'
            return httpx.Response(200, content=sse.encode(), headers={'content-type': 'text/event-stream'})

        real = httpx.AsyncClient
        engine = online_llm.OnlineEngine()
        async def run():
            return [t async for t in engine.stream([{'role': 'user', 'content': 'hi'}])]
        with patch.object(online_llm, 'online_key', return_value='test-key'), \
             patch.object(online_llm.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler), **kw)), \
             self.assertLogs('brain.online', level='WARNING'):
            self.assertEqual(asyncio.run(run()), ['ok'])
            self.assertTrue(engine.available())  # one busy model does not switch the brain off
        self.assertEqual(models, ['gemini-3.5-flash-lite', 'gemini-flash-lite-latest'])

    def test_not_available_without_key(self):
        from app.services.local_ai import online_llm
        with patch.object(online_llm, 'online_key', return_value=''):
            self.assertFalse(online_llm.OnlineEngine().available())


class HedgedRequestTests(unittest.TestCase):
    def _engine(self, handler):
        import httpx
        from app.services.local_ai import online_llm
        real = httpx.AsyncClient
        engine = online_llm.OnlineEngine()
        patches = [patch.object(online_llm, 'online_key', return_value='test-key'),
                   patch.object(online_llm.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler), **kw))]
        return engine, patches

    @staticmethod
    def sse(text):
        return ('data: ' + json.dumps({'choices': [{'delta': {'content': text}}]}) + '\n\ndata: [DONE]\n\n').encode()

    def test_slow_first_model_is_overtaken_by_the_second(self):
        import httpx, time
        async def handler(request):
            model = json.loads(request.content)['model']
            if model == 'gemini-3.5-flash-lite':
                await asyncio.sleep(6)  # overloaded
            return httpx.Response(200, content=self.sse(f'from {model}'), headers={'content-type': 'text/event-stream'})
        engine, patches = self._engine(handler)
        for item in patches: item.start()
        try:
            started = time.monotonic()
            out = asyncio.run(self._collect(engine))
            took = time.monotonic() - started
        finally:
            for item in patches: item.stop()
        self.assertEqual(out, ['from gemini-flash-lite-latest'])
        self.assertLess(took, 5)  # ~3 s hedge, not the slow model's 6 s

    def test_both_models_failing_raises(self):
        import httpx
        def handler(request):
            raise httpx.ReadTimeout('slow internet', request=request)
        engine, patches = self._engine(handler)
        for item in patches: item.start()
        try:
            with self.assertLogs('brain.online', level='WARNING'), self.assertRaises(RuntimeError):
                asyncio.run(self._collect(engine))
        finally:
            for item in patches: item.stop()

    @staticmethod
    async def _collect(engine):
        return [t async for t in engine.stream([{'role': 'user', 'content': 'hi'}])]


class OnlineFallbackTests(unittest.TestCase):
    class Local:
        async def load(self): pass
        async def stream(self, messages, max_tokens):
            yield 'local answer'
        async def unload(self): pass

    def _run(self, local_fallback):
        from app.services.local_ai.llm_manager import LLMManager
        from app.services.local_ai import llm_manager as module
        from app.settings import get_settings

        async def broken(messages):
            raise RuntimeError('no internet')
            yield

        manager = LLMManager(engine=self.Local())
        async def run():
            out = [t async for t in manager.stream([], 10, online_messages=[{'role': 'user', 'content': 'hi'}])]
            if manager.idle_task: manager.idle_task.cancel()
            return out
        with patch.object(module.online, 'available', return_value=True), \
             patch.object(module.online, 'stream', broken), \
             patch.dict(get_settings()['llm'], {'local_fallback': local_fallback}), self.assertLogs('brain.llm', level='WARNING'):
            return asyncio.run(run()), manager.last_source

    def test_default_says_internet_is_slow_instead_of_a_weak_local_answer(self):
        out, source = self._run(False)
        self.assertIn('इंटरनेट', out[0])
        self.assertEqual(source, 'internet-slow')

    def test_local_model_answers_when_allowed(self):
        self.assertEqual(self._run(True), (['local answer'], 'local-ai'))


if __name__ == '__main__': unittest.main()
