"""Online speech-to-text through the online brain's provider (Gemini audio input).

On an old 2-core laptop, local Whisper took 10 s to minutes per sentence while the camera
analysis was running, and it wrote Hindi in broken Roman letters. Gemini returns proper
Devanagari Hindi (English words in English) in about 1-2 s. The recording (16 kHz mono WAV) is
sent to the provider set in [online_ai]; local Whisper takes over when that fails or is off.
"""
import base64
import io
import logging
import time
import wave

import httpx
import numpy as np

from ...settings import get_settings, online_key
from ..local_ai.online_llm import online

log = logging.getLogger('audio.stt.online')
SILENCE = '<silence>'
RETRY_SECONDS = 30
PROMPT = ('You are a speech-to-text engine for a person in India who speaks Hindi, Hinglish or English. '
          'Transcribe exactly what they say in this recording. Write Hindi words in Devanagari and English words '
          'in English letters, exactly as spoken. Do not translate, do not answer, do not add or fix anything, no '
          'quotes or labels. If there is no clear human speech (silence, noise, music, a cough), reply exactly '
          f'{SILENCE}.')


def wav_bytes(audio):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
    return buffer.getvalue()


class OnlineSTT:
    def __init__(self):
        self.failed_at = 0.0

    def available(self):
        cfg = get_settings()
        return (cfg['stt']['provider'] == 'auto' and cfg['online_ai']['provider'] in ('gemini', 'openai')
                and online.available() and time.monotonic() - self.failed_at >= RETRY_SECONDS)

    def _ask(self, base_url, model, payload, prompt):
        response = httpx.post(base_url + '/chat/completions', timeout=httpx.Timeout(8, connect=4),
                              headers={'Authorization': f'Bearer {online_key()}'}, json={
            'model': model, 'temperature': 0, 'max_tokens': 400,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'input_audio', 'input_audio': {'data': payload, 'format': 'wav'}}]}]})
        if response.status_code >= 400:
            raise RuntimeError(f'HTTP {response.status_code}')
        text = (response.json()['choices'][0]['message'].get('content') or '').strip().strip('"“”\'` ').strip()
        return '' if not text or SILENCE in text.lower() or text.lower() in ('silence', '[silence]') else text

    def transcribe(self, audio, hints=''):
        """audio: float32 16 kHz mono. Returns the text ('' for no speech); raises on failure.
        Hedged like the brain: a second model is asked if the first is slow (>2.5 s) or fails."""
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        llm = online.config()
        models = list(dict.fromkeys([get_settings()['stt']['online_model'] or llm['models'][0]] + llm['models']))[:2]
        payload = base64.b64encode(wav_bytes(audio)).decode('ascii')
        prompt = PROMPT + (f' Names that may be spoken: {hints}.' if hints else '')
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            pending = {pool.submit(self._ask, llm['base_url'], models[0], payload, prompt): models[0]}
            done, _ = wait(pending, timeout=2.5)
            if (not done or next(iter(done)).exception()) and len(models) > 1:
                pending[pool.submit(self._ask, llm['base_url'], models[1], payload, prompt)] = models[1]
            errors = []
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    model = pending.pop(future)
                    if future.exception() is None:
                        return future.result()
                    errors.append(future.exception())
                    log.warning('Online speech recognition with %s failed (%s)', model, str(future.exception())[:120])
            self.failed_at = time.monotonic()
            raise RuntimeError(f'Online speech recognition failed: {errors[-1] if errors else "no answer"}')
        finally:
            pool.shutdown(wait=False, cancel_futures=True)


online_stt = OnlineSTT()
