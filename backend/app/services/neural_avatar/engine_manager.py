"""One lazy worker process and one active generation, with bounded disk cache."""
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import subprocess
import threading
from uuid import uuid4
from .atlas import ATLAS_VERSION
from ...vision.service import service as vision

ROOT=Path(__file__).resolve().parents[4]
PRESETS={'fast':{'resolution':128,'fps':4},'balanced':{'resolution':256,'fps':8},'quality':{'resolution':256,'fps':12}}
TERMINAL={'READY','ERROR','CANCELLED'}


class EngineManager:
    def __init__(self):
        self.lock=threading.RLock();self.jobs=OrderedDict();self.process=None;self.active=None;self.log=None

    def _worker(self):
        if self.process is not None and self.process.poll() is None:return self.process
        venv=ROOT/'.tools'/'neural-venv'
        runtime=venv/'Scripts'/'python.exe' if (venv/'Scripts'/'python.exe').exists() else venv/'bin'/'python'
        if not runtime.exists():raise RuntimeError('Optional neural runtime is not installed')
        self.log=(ROOT/'.tools'/'neural-worker.log').open('a',encoding='utf-8')
        self.process=subprocess.Popen([str(runtime),'-u',str(Path(__file__).with_name('worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return self.process

    def start(self,avatar_id,image,metadata,neural_dir,action,quality,controls=None,duration=4):
        from ...settings import get_settings
        if not get_settings()['neural']['enabled']:
            # Raspberry Pi: rendering poses would take 20-30 min and heat the board.
            raise RuntimeError('The neural engine is turned off on this device ([neural] enabled).')
        if not (ROOT/'.tools'/'neural-evaluation'/'revision.txt').is_file():
            raise RuntimeError('Optional neural runtime is not installed')
        preset=PRESETS[quality]
        source_hash=hashlib.sha256(image.read_bytes()).hexdigest()
        revision=(ROOT/'.tools'/'neural-evaluation'/'revision.txt').read_text().strip()
        key_metadata = {name:metadata[name] for name in ['face_box','landmarks']} if action=='ATLAS' else metadata
        key_parts=[source_hash,key_metadata,revision,action,quality,controls,duration,3]
        previous_key=hashlib.sha256(json.dumps(key_parts,sort_keys=True).encode()).hexdigest()
        key=hashlib.sha256(json.dumps(key_parts+[ATLAS_VERSION],sort_keys=True).encode()).hexdigest() if action=='ATLAS' else previous_key
        cache=ROOT/'avatar_data'/'neural_atlases' if action=='ATLAS' else neural_dir/'cache'
        cache.mkdir(parents=True,exist_ok=True);output=cache/f"{key}.{'png' if action=='ATLAS' else 'mp4'}"
        ready=output.is_file() and (action!='ATLAS' or output.with_suffix('.json').is_file())
        with self.lock:
            if self.active and not ready:
                # A reload or second tab asking for the same result joins the running job
                # instead of failing with "busy"; it is cancelled only when nobody watches it.
                running=self.jobs.get(self.active)
                if running and running['cache_key']==key and running['avatar_id']==avatar_id and running['state'] not in TERMINAL:
                    running['watchers']=running.get('watchers',1)+1
                    return dict(running)
                raise RuntimeError('Neural engine is busy')
            job_id=str(uuid4());job={'job_id':job_id,'avatar_id':avatar_id,'state':'READY' if ready else 'LOADING MODEL','progress':1 if ready else 0,'cached':ready,'cache_key':key,'quality':quality,'action':action,'playback_mode':'CACHED POSES' if action=='ATLAS' else 'PRE-RENDER','watchers':1}
            self.jobs[job_id]=job
            while len(self.jobs)>24:self.jobs.popitem(last=False)
            if ready:output.touch();return dict(job)
            self.active=job_id
            command={'job_id':job_id,'image':str(image),'metadata':metadata,'neural_dir':str(neural_dir),'source_hash':source_hash,'output':str(output),'action':action,'controls':controls or [],'duration':duration,**preset}
            if action=='ATLAS':
                previous_version_key=hashlib.sha256(json.dumps(key_parts+[ATLAS_VERSION-1],sort_keys=True).encode()).hexdigest()
                candidate=cache/f'{previous_version_key}.png'
                command['reuse_atlas']=str(candidate if candidate.is_file() else cache/f'{previous_key}.png')
            threading.Thread(target=self._generate,args=(command,job),daemon=True).start()
            return dict(job)

    def _generate(self,command,job):
        # The camera's feeling analysis would take CPU from pose rendering (2-4x slower measured).
        with vision.pause():
            self._generate_paused(command,job)

    def _generate_paused(self,command,job):
        try:
            with self.lock:
                process=self._worker()
                process.stdin.write(json.dumps(command)+'\n');process.stdin.flush()
                if job.get('cancel_requested'):
                    process.stdin.write(json.dumps({'job_id':job['job_id'],'cancel':True})+'\n');process.stdin.flush()
            for line in process.stdout:
                event=json.loads(line)
                if event.get('job_id')!=job['job_id']:continue
                with self.lock:job.update(event)
                if event['state'] in TERMINAL:break
            else:raise RuntimeError('Neural worker exited before completing generation')
            if job['state']=='READY':
                folder=Path(command['output']).parent
                files=sorted(folder.glob('*.png' if command['action']=='ATLAS' else '*.mp4'),key=lambda p:p.stat().st_mtime,reverse=True)
                total=0
                for index,file in enumerate(files):
                    total+=file.stat().st_size
                    if index>=8 or total>512*1024*1024:
                        file.unlink(missing_ok=True)
                        if command['action']=='ATLAS':file.with_suffix('.json').unlink(missing_ok=True)
        except Exception as error:
            with self.lock:job.update(state='ERROR',error=str(error))
        finally:
            with self.lock:self.active=None

    def status(self,job_id,avatar_id):
        with self.lock:
            job=self.jobs.get(job_id)
            if job is None or job['avatar_id']!=avatar_id:raise KeyError(job_id)
            return dict(job)

    def cancel(self,job_id,avatar_id):
        with self.lock:
            job=self.jobs.get(job_id)
            if job is None or job['avatar_id']!=avatar_id:raise KeyError(job_id)
            if job['state'] in TERMINAL:return dict(job)
            if job.get('watchers',1)>1:
                job['watchers']-=1
                return dict(job)
            job['cancel_requested']=True
            if self.process is not None and self.process.poll() is None:
                self.process.stdin.write(json.dumps({'job_id':job_id,'cancel':True})+'\n');self.process.stdin.flush()
            return dict(job)

    def shutdown(self):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                if self.active:
                    self.process.stdin.write(json.dumps({'job_id':self.active,'cancel':True})+'\n');self.process.stdin.flush()
                self.process.stdin.close()
                try:self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:self.process.terminate()
            if self.log:self.log.close()
            self.process=None

manager=EngineManager()
