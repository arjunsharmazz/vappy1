"""Actual preview job, cache hit and cancellation through the running local API."""
import json
from pathlib import Path
import shutil
import time
from uuid import UUID
import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    c = httpx.Client(base_url='http://127.0.0.1:8000', trust_env=False, timeout=30)
    avatar_id = None
    try:
        with (ROOT / '.tools/face-test.jpg').open('rb') as image:
            r = c.post('/avatar/upload', files={'file': ('face.jpg', image, 'image/jpeg')})
        r.raise_for_status(); avatar_id = r.json()['avatar_id']
        endpoint = f'/avatar/{avatar_id}/neural/jobs'
        r = c.post(endpoint, json={'action': 'SMILE', 'quality': 'fast', 'duration': 1})
        r.raise_for_status(); job = r.json(); started = time.perf_counter()
        while job['state'] not in ['READY', 'ERROR', 'CANCELLED']:
            if time.perf_counter() - started > 150: raise TimeoutError('Neural preview exceeded 150 seconds')
            time.sleep(.5); r = c.get(endpoint + '/' + job['job_id']); r.raise_for_status(); job = r.json()
        assert job['state'] == 'READY', job
        video = c.get(job['video_url']); video.raise_for_status()
        assert video.headers['content-type'] == 'video/mp4' and len(video.content) > 1000
        repeat = c.post(endpoint, json={'action': 'SMILE', 'quality': 'fast', 'duration': 1}).json()
        assert repeat['cached'] and repeat['state'] == 'READY'
        active = c.post(endpoint, json={'action': 'LOOK_LEFT', 'quality': 'fast', 'duration': 1}).json()
        cancel = c.post(endpoint + '/' + active['job_id'] + '/cancel'); cancel.raise_for_status()
        for _ in range(120):
            active = c.get(endpoint + '/' + active['job_id']).json()
            if active['state'] in ['CANCELLED', 'ERROR', 'READY']: break
            time.sleep(.5)
        assert active['state'] == 'CANCELLED', active
        report_file = ROOT / 'neural_integration_benchmark.json'
        report = json.loads(report_file.read_text()) if report_file.exists() else {}
        report['api_check'] = {'status': 'passed', 'job': job, 'video_bytes': len(video.content),
                               'cache_hit': True, 'cancelled': True}
        report_file.write_text(json.dumps(report, indent=2))
        print('PASS real CPU preview, local video, cache reuse and cancellation', flush=True)
    finally:
        if avatar_id:
            assert str(UUID(avatar_id)) == avatar_id
            folder = ROOT / 'avatar_data' / avatar_id
            if folder.is_dir(): shutil.rmtree(folder)
            (ROOT / 'uploads' / (avatar_id + '.jpg')).unlink(missing_ok=True)
        c.close()


if __name__ == '__main__': main()
