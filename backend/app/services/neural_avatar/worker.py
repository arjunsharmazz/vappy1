"""Persistent local CPU worker. JSON-lines stdin/stdout; no network access here."""
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from app.services.neural_avatar.model_loader import LivePortraitCPU
from app.services.neural_avatar.base_engine import MotionControl


def emit(**event):
    print(json.dumps(event),flush=True)


def main():
    import imageio_ffmpeg
    import psutil
    import numpy as np
    jobs=queue.Queue();events={};lock=threading.Lock()
    def read_commands():
        for line in sys.stdin:
            command=json.loads(line)
            with lock:
                flag=events.setdefault(command['job_id'],threading.Event())
            if command.get('cancel'):flag.set()
            else:jobs.put((command,flag))
        jobs.put(None)
    threading.Thread(target=read_commands,daemon=True).start()
    engine=LivePortraitCPU();prepared_key=None;prepared=None
    try:
        while True:
            try:item=jobs.get(timeout=300)
            except queue.Empty:
                prepared=None;prepared_key=None;engine.unload()
                continue
            if item is None:break
            command,cancel=item;job_id=command['job_id'];writer=None;pending=Path(command['output']).with_suffix('.pending.mp4')
            terminal=None
            def check():
                if cancel.is_set():raise InterruptedError('Generation cancelled')
                if psutil.Process().memory_info().rss>10*1024**3:raise MemoryError('Neural process exceeded 10 GiB RAM limit')
            try:
                check();emit(job_id=job_id,state='LOADING MODEL',progress=0)
                model=engine.load();check()
                emit(job_id=job_id,state='PREPARING AVATAR',progress=.02,model=model)
                key=(command['image'],command['resolution'],command['source_hash'])
                if prepared_key!=key:
                    prepared=None
                    prepared=engine.prepare_avatar(Path(command['image']),command['metadata'],Path(command['neural_dir']),command['resolution'])
                    prepared_key=key
                check()
                if command['action']=='ATLAS':
                    from app.services.neural_avatar.atlas import generate_atlas
                    details=generate_atlas(engine,prepared,command['metadata'],command['output'],check,
                        lambda index,total:emit(job_id=job_id,state='PROCESSING FRAMES',progress=.04+.94*index/total,frame=index,total_frames=total),command.get('reuse_atlas'),
                        partial=lambda:emit(job_id=job_id,state='PROCESSING FRAMES',partial_ready=True))
                    emit(job_id=job_id,state='READY',progress=1,generation_seconds=details['generation_seconds'])
                    continue
                fps=command['fps'];duration=command['duration'];count=max(1,math.ceil(duration*fps))
                height,width=prepared['image'].shape[:2]
                # Even-sized H.264 output. The final row/column is edge padded.
                out_width=width+(width%2);out_height=height+(height%2)
                pending.parent.mkdir(parents=True,exist_ok=True)
                started=time.perf_counter();samples=[]
                emit(job_id=job_id,state='GENERATING',progress=.04,total_frames=count)
                controls=command.get('controls',[])
                for index in range(count):
                    check();t=index/fps;p=index/max(1,count-1);action=command['action']
                    blink=math.sin(math.pi*min(1,max(0,(t-2.1)/.35)))**2 if 2.1<t<2.45 else 0
                    control=MotionControl(blink=blink,yaw=.6*math.sin(2*math.pi*p))
                    if action=='BLINK':control=MotionControl(blink=math.sin(math.pi*p)**4)
                    elif action=='SMILE':control=MotionControl(smile=.55*math.sin(math.pi*p)**2)
                    elif action in ['LOOK_LEFT','LOOK_RIGHT']:
                        direction=(-1 if action=='LOOK_LEFT' else 1)*math.sin(math.pi*p)**2
                        control=MotionControl(yaw=2*direction,gaze_x=6*direction)
                    elif action=='SPEAKING':
                        point=controls[min(index,len(controls)-1)]
                        control=MotionControl(blink=blink,mouth_open=point['mouth_open'],mouth_width=point['mouth_width'],lip_roundness=point['lip_roundness'],pitch=.3*math.sin(2*math.pi*p),mouth_only=True)
                    frame_start=time.perf_counter();rgb=engine.render(prepared,control);check()
                    if out_width!=width or out_height!=height:rgb=np.pad(rgb,((0,out_height-height),(0,out_width-width),(0,0)),mode='edge')
                    if writer is None:
                        writer=imageio_ffmpeg.write_frames(str(pending),(out_width,out_height),fps=fps,codec='libx264',pix_fmt_in='rgb24',pix_fmt_out='yuv420p',quality=7,macro_block_size=1,output_params=['-movflags','+faststart','-threads','2'])
                        writer.send(None)
                    writer.send(rgb);del rgb
                    samples.append(time.perf_counter()-frame_start)
                    emit(job_id=job_id,state='PROCESSING FRAMES',progress=.04+.94*(index+1)/count,frame=index+1,total_frames=count,rss_bytes=psutil.Process().memory_info().rss)
                writer.close();writer=None;check();pending.replace(command['output'])
                emit(job_id=job_id,state='READY',progress=1,generation_seconds=time.perf_counter()-started,mean_frame_seconds=sum(samples)/len(samples),duration=count/fps,preprocessing_seconds=prepared['prepare_seconds'])
            except InterruptedError:
                terminal={'state':'CANCELLED','progress':0}
            except Exception as error:
                terminal={'state':'ERROR','error':f'{type(error).__name__}: {error}'}
            finally:
                if writer is not None:
                    try:writer.close()
                    except Exception:pass
                pending.unlink(missing_ok=True)
                with lock:events.pop(job_id,None)
                if terminal:emit(job_id=job_id,**terminal)
    finally:engine.unload()

if __name__=='__main__':main()
