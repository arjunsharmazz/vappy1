"""Real loopback STT/LLM/TTS measurements; no model mocking or remote inference."""
import json
from pathlib import Path
import statistics
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import psutil

ROOT = Path(__file__).resolve().parents[2]


def main():
    client = httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False, timeout=180)
    report = {'measured_at_utc': datetime.now(timezone.utc).isoformat(),
              'kind': 'actual local CPU measurements', 'stt_engine': 'faster-whisper 1.2.1 / CTranslate2',
              'stt_model': 'Whisper Tiny multilingual (39M)', 'stt_quantization': 'int8 compute',
              'llm_runtime': 'llama.cpp', 'llm_model': 'Qwen3-0.6B', 'llm_quantization': 'Q8_0',
              'model_files': json.loads((ROOT / '.tools/models/manifest.json').read_text()),
              'runs': [], 'limitations': ['Synthesized English fixture, not a human microphone accuracy test.',
                  'Hindi/Hinglish audio accuracy requires representative recordings.',
                  'API timings exclude browser playback; see browser_runs when present.']}
    runtime = ROOT / '.tools/llama-cpp/release.json'
    if runtime.exists(): report['runtime_release'] = json.loads(runtime.read_text())
    avatar_id = None
    samples = []; ended = threading.Event()
    def sample():
        while not ended.wait(.2):
            try:
                match = next(c for c in psutil.net_connections('tcp') if c.status == 'LISTEN' and c.laddr.port == 8000)
                process = psutil.Process(match.pid)
                rss = sum(p.memory_info().rss for p in [process, *process.children(recursive=True)] if p.is_running())
                samples.append({'rss_bytes': rss, 'system_cpu_percent': psutil.cpu_percent()})
            except (psutil.Error, StopIteration): pass
    thread = threading.Thread(target=sample, daemon=True); thread.start()
    try:
        with (ROOT / '.tools/face-test.jpg').open('rb') as image:
            result = client.post('/avatar/upload', files={'file': ('face.jpg', image, 'image/jpeg')})
        result.raise_for_status(); avatar_id = result.json()['avatar_id']
        session = str(uuid4())
        for index, text in enumerate(['My name is Arjun.', 'What is my name?', 'नमस्ते, आप कैसे हैं?', 'Mujhe ek short greeting do.']):
            started = time.perf_counter(); first = None; answer = ''; timings = {}
            with client.stream('POST', f'/avatar/{avatar_id}/conversation', json={
                'session_id': session, 'turn_id': str(uuid4()), 'text': text, 'response_length': 'short',
            }) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    item = json.loads(line)
                    if item['type'] == 'error': raise RuntimeError(item['message'])
                    if item['type'] == 'token':
                        if first is None: first = time.perf_counter() - started
                        answer += item['text']
                    if item['type'] == 'done': timings = item['metrics']
            run = {'input': text, 'response': answer, 'llm_client_first_token_seconds': first, **timings}
            if index == 1:
                run['memory_passed'] = 'arjun' in answer.lower()
                assert run['memory_passed'], answer
            report['runs'].append(run)
            print('LLM case', index + 1, 'seconds', round(timings['llm_total_seconds'], 3), flush=True)
        clear = client.post(f'/avatar/{avatar_id}/conversation/clear', json={'session_id': session})
        clear.raise_for_status(); report['clear_status'] = clear.status_code
        # Reuse actual Windows speech as a reproducible local recognition fixture.
        t = time.perf_counter()
        voice = client.post(f'/avatar/{avatar_id}/speak', json={'text': 'Hello, how are you? My name is Arjun.'})
        voice.raise_for_status(); report['fixture_tts_seconds'] = time.perf_counter() - t
        wav = client.get(voice.json()['audio_url']); wav.raise_for_status()
        (ROOT / '.tools/conversation-fixture.wav').write_bytes(wav.content)
        for label in ['cold', 'warm']:
            started = time.perf_counter()
            result = client.post(f'/avatar/{avatar_id}/listen', files={'file': ('fixture.wav', wav.content, 'audio/wav')}, data={'language': 'en'})
            result.raise_for_status()
            report.setdefault('stt_runs', []).append({'load': label, **result.json(), 'client_seconds': time.perf_counter() - started})
            print('STT', label, round(result.json()['stt_seconds'], 3), flush=True)
        report['status'] = 'passed'
    except Exception as error:
        report['status'] = 'failed'; report['error'] = str(error)
        raise
    finally:
        ended.set(); thread.join(2)
        report['resource_sample_count'] = len(samples)
        report['peak_backend_tree_rss_bytes'] = max((s['rss_bytes'] for s in samples), default=None)
        report['mean_system_cpu_percent'] = statistics.mean(s['system_cpu_percent'] for s in samples) if samples else None
        (ROOT / 'conversation_benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if avatar_id:
            # Only the unique avatar created by this run is removed.
            import shutil
            from uuid import UUID
            assert str(UUID(avatar_id)) == avatar_id
            folder = ROOT / 'avatar_data' / avatar_id
            if folder.is_dir(): shutil.rmtree(folder)
            (ROOT / 'uploads' / (avatar_id + '.jpg')).unlink(missing_ok=True)
        client.close()


if __name__ == '__main__': main()
