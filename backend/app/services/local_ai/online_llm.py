"""Online brain: any OpenAI-compatible chat API (Google Gemini, Groq, OpenAI).

Used when an API key is set in config/.env; otherwise, or when the internet is down, the local
llama.cpp model answers instead (see llm_manager). Only the conversation text is sent.

Popular models are sometimes overloaded (HTTP 503) or slow to start. If the first word does not
arrive within `first_word_seconds`, the next model in `fallback_models` is tried at once, so the
person is never left waiting half a minute.
"""
import asyncio
import json
import logging
import time

import httpx

from ...settings import get_settings, online_key

log = logging.getLogger('brain.online')

# (base URL, default model, default fallbacks). Measured on this laptop in Nov 2026:
# gemini-3.5-flash-lite starts speaking in ~1.5 s with natural Hindi; gemini-3.5-flash is
# similar quality but was often ~25 s while Google's servers were busy.
PRESETS = {
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/openai', 'gemini-3.5-flash-lite',
               ['gemini-flash-lite-latest', 'gemini-3.6-flash']),
    'groq': ('https://api.groq.com/openai/v1', 'llama-3.3-70b-versatile', []),
    'openai': ('https://api.openai.com/v1', 'gpt-5-mini', []),
}
# After every model failed (no internet, quota) the local model answers for a while instead of
# every reply first waiting for network timeouts.
RETRY_SECONDS = 20
# No first word from the first model within this time → the second model is asked as well.
HEDGE_SECONDS = 3.0
RETRYABLE = {408, 429, 500, 502, 503, 504}


class Retryable(Exception):
    pass


class OnlineEngine:
    def __init__(self):
        self.failed_at = 0.0

    @staticmethod
    def config():
        cfg = get_settings()['online_ai']
        base, model, fallbacks = PRESETS.get(cfg['provider'], ('', '', []))
        configured = [m.strip() for m in cfg['fallback_models'].split(',') if m.strip()] if cfg['fallback_models'] else fallbacks
        model = cfg['model'] or model
        return {**cfg, 'base_url': (cfg['base_url'] or base).rstrip('/'), 'model': model,
                'models': [model] + [m for m in configured if m != model]}

    def configured(self):
        cfg = self.config()
        return bool(cfg['provider'] != 'none' and online_key() and cfg['base_url'] and cfg['model'])

    def available(self):
        return self.configured() and time.monotonic() - self.failed_at >= RETRY_SECONDS

    def name(self):
        cfg = self.config()
        return f"{cfg['provider']}:{cfg['model']}"

    async def stream(self, messages):
        """Hedged: ask the first model; if it has not started answering within HEDGE_SECONDS (or it
        fails), ask the second one too and use whichever answers first. Busy/slow servers were the
        main cause of long waits (measured 11 s, 503s, timeouts on single models)."""
        cfg = self.config()
        models = cfg['models'][:2]
        queue = asyncio.Queue()

        async def run(index):
            try:
                async for token in self._stream_model(cfg, models[index], messages):
                    await queue.put((index, 'token', token))
                await queue.put((index, 'done', None))
            except Exception as error:  # reported through the queue
                await queue.put((index, 'error', error))

        tasks = {0: asyncio.create_task(run(0))}
        deadline = time.monotonic() + HEDGE_SECONDS
        winner, failures = None, []
        try:
            while True:
                hedge_possible = winner is None and len(models) > 1 and 1 not in tasks
                wait = max(0.0, deadline - time.monotonic()) if hedge_possible else None
                try:
                    index, kind, value = await asyncio.wait_for(queue.get(), wait)
                except asyncio.TimeoutError:
                    log.info('Model %s slow to start; asking %s too', models[0], models[1])
                    tasks[1] = asyncio.create_task(run(1))
                    continue
                if winner is None:
                    if kind == 'token':
                        winner = index
                        self.used = models[index]
                        for other, task in tasks.items():
                            if other != index:
                                task.cancel()
                        yield value
                    elif kind == 'error':
                        failures.append(value)
                        log.warning('Online model %s failed (%s)', models[index], str(value)[:120] or type(value).__name__)
                        if hedge_possible:
                            tasks[1] = asyncio.create_task(run(1))
                        elif len(failures) >= len(tasks):
                            self.failed_at = time.monotonic()
                            raise RuntimeError(f'Online AI unavailable: {failures[-1]}')
                    else:  # an empty answer
                        return
                elif index == winner:
                    if kind == 'token':
                        yield value
                    elif kind == 'done':
                        return
                    else:
                        raise RuntimeError('The online AI stopped mid-answer.')
        finally:
            for task in tasks.values():
                task.cancel()

    async def _stream_model(self, cfg, model, messages):
        body = {'model': model, 'messages': messages, 'stream': True,
                'max_tokens': cfg['max_tokens'], 'temperature': cfg['temperature']}
        # Gemini 3 models always think a little by themselves; a set level asks for more (slower).
        if cfg['thinking'] and cfg['provider'] in ('gemini', 'openai'):
            body['reasoning_effort'] = cfg['thinking']
        headers = {'Authorization': f'Bearer {online_key()}'}
        # The read timeout bounds the wait for the first word (and any later pause).
        timeout = httpx.Timeout(max(3, cfg['first_word_seconds']), connect=5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in (1, 2):
                async with client.stream('POST', cfg['base_url'] + '/chat/completions',
                                         json=body, headers=headers) as response:
                    if response.status_code == 400 and attempt == 1 and 'reasoning_effort' in body:
                        # This model has no adjustable thinking; ask again without it.
                        await response.aread()
                        body.pop('reasoning_effort')
                        continue
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode('utf-8', 'replace')[:300]
                        kind = Retryable if response.status_code in RETRYABLE or response.status_code == 404 else RuntimeError
                        raise kind(f'HTTP {response.status_code}: {detail}')
                    async for line in response.aiter_lines():
                        if not line.startswith('data: '):
                            continue
                        if line[6:].strip() == '[DONE]':
                            return
                        data = json.loads(line[6:])
                        choices = data.get('choices') or [{}]
                        content = (choices[0].get('delta') or {}).get('content')
                        if content:
                            yield content
                    return


online = OnlineEngine()
