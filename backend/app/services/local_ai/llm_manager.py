"""One CPU-only llama.cpp child; all inference HTTP is hard-bound to loopback."""
import asyncio
import json
import logging
from pathlib import Path
import subprocess
import time

import httpx

from .base_llm import LanguageModelEngine
from .online_llm import online
from ...settings import get_settings

ROOT = Path(__file__).resolve().parents[4]
log = logging.getLogger('brain.llm')


class LlamaCppEngine(LanguageModelEngine):
    def __init__(self):
        cfg = get_settings()['llm']
        self.process = None
        self.log = None
        self.enabled = cfg['enabled']
        self.model = Path(cfg['model_path'])
        self.executable = Path(cfg['executable'])
        self.port = cfg['port']
        self.threads = cfg['threads']
        self.context = cfg['context']
        self.temperature = cfg['temperature']
        self.base_url = f'http://127.0.0.1:{self.port}'

    async def load(self):
        if self.process and self.process.poll() is None:
            return
        if not self.enabled:
            raise RuntimeError('Local AI is disabled in config/settings.toml ([llm] enabled = false).')
        if not self.model.is_file() or not self.executable.is_file():
            log.error('LLM files missing: model=%s exists=%s, executable=%s exists=%s',
                      self.model, self.model.is_file(), self.executable, self.executable.is_file())
            raise RuntimeError('Local AI unavailable. Run the Phase 6 setup command.')
        async with httpx.AsyncClient(trust_env=False, timeout=1) as client:
            try:
                await client.get(self.base_url + '/health')
            except httpx.TransportError:
                pass
            else:
                raise RuntimeError(f'Local AI port {self.port} is occupied. Stop the other instance before retrying.')
        if self.log:
            self.log.close()
        self.log = (ROOT / '.tools/llama-server.log').open('ab')
        log.info('Starting llama.cpp: %s (threads=%d, context=%d)', self.model.name, self.threads, self.context)
        self.process = subprocess.Popen([
            str(self.executable), '-m', str(self.model), '--host', '127.0.0.1', '--port', str(self.port),
            '-c', str(self.context), '-t', str(self.threads), '-tb', str(self.threads), '-ngl', '0', '-np', '1',
            '--jinja', '--chat-template-kwargs', '{"enable_thinking":false}',
        ], stdout=self.log, stderr=self.log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                for _ in range(240):
                    if self.process.poll() is not None:
                        raise RuntimeError('Local AI could not start. See .tools/llama-server.log.')
                    try:
                        response = await client.get(self.base_url + '/health')
                        if response.status_code == 200:
                            return
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(.25)
            raise RuntimeError('Local AI model loading timed out.')
        except BaseException:
            await self.unload()
            raise

    async def stream(self, messages, max_tokens):
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(120, connect=3)) as client:
            async with client.stream('POST', self.base_url + '/v1/chat/completions', json={
                'messages': messages, 'stream': True, 'max_tokens': max_tokens,
                'temperature': self.temperature, 'seed': 42,
                'chat_template_kwargs': {'enable_thinking': False},
            }) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):
                        continue
                    if line[6:] == '[DONE]':
                        break
                    data = json.loads(line[6:])
                    content = data.get('choices', [{}])[0].get('delta', {}).get('content')
                    if content:
                        yield content

    async def unload(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, 5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait)
        self.process = None
        if self.log:
            self.log.close()
            self.log = None


class LLMManager:
    def __init__(self, engine=None):
        self.engine = engine or LlamaCppEngine()
        self.lock = asyncio.Lock()
        self.idle_task = None
        self.last_source = 'local-ai'

    def online_ready(self):
        return online.available()

    async def stream(self, messages, max_tokens, online_messages=None):
        """Online brain first (when configured and reachable); the local model answers when it
        is not configured, the internet is down, or it fails before saying anything."""
        # Without the local model as a fallback, the online brain is always tried (no back-off).
        use_online = online.available() or (online.configured() and not get_settings()['llm']['local_fallback'])
        if online_messages is not None and use_online:
            started = False
            self.last_source = 'online-ai:' + online.name()
            try:
                async for token in online.stream(online_messages):
                    started = True
                    yield token
                return
            except Exception as error:
                if started:
                    raise RuntimeError('The online AI stopped mid-answer. Please ask again.') from error
                log.warning('Online AI unavailable (%s)', str(error)[:200] or type(error).__name__)
                if not get_settings()['llm']['local_fallback']:
                    # The tiny laptop model answered nonsense and loaded the CPU: say so honestly.
                    self.last_source = 'internet-slow'
                    yield 'माफ़ कीजिए, अभी इंटरनेट थोड़ा धीमा है। एक बार फिर से बोलिए?'
                    return
        self.last_source = 'local-ai'
        async for token in self._local(messages, max_tokens):
            yield token

    async def _local(self, messages, max_tokens):
        if self.lock.locked():
            raise RuntimeError('Local AI is busy. Please retry shortly.')
        async with self.lock:
            if self.idle_task:
                self.idle_task.cancel()
            try:
                await self.engine.load()
                async for token in self.engine.stream(messages, max_tokens):
                    yield token
            finally:
                self.idle_task = asyncio.create_task(self._unload_when_idle())

    async def _unload_when_idle(self):
        await asyncio.sleep(get_settings()['llm']['idle_unload_seconds'])
        async with self.lock:
            await self.engine.unload()

    async def unload(self):
        if self.idle_task:
            self.idle_task.cancel()
        async with self.lock:
            await self.engine.unload()


manager = LLMManager()
