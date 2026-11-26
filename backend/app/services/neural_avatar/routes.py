"""Optional routes; registered only when the neural integration is enabled."""
import math
import re
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from .engine_manager import manager,PRESETS
from ..avatar_store import read_avatar
from ...config import AVATAR_DATA,UPLOADS

router=APIRouter()


@router.on_event('shutdown')
def shutdown_neural():
    manager.shutdown()


class NeuralControl(BaseModel):
    mouth_open:float=Field(ge=0,le=.75,allow_inf_nan=False)
    mouth_width:float=Field(ge=.75,le=1.15,allow_inf_nan=False)
    lip_roundness:float=Field(ge=0,le=1,allow_inf_nan=False)


class NeuralRequest(BaseModel):
    action:Literal['IDLE','BLINK','SMILE','LOOK_LEFT','LOOK_RIGHT','SPEAKING']='IDLE'
    quality:Literal['fast','balanced','quality']='balanced'
    duration:float=Field(default=4,gt=0,le=30,allow_inf_nan=False)
    controls:list[NeuralControl]=Field(default_factory=list,max_length=360)

    @model_validator(mode='after')
    def validate_frames(self):
        if self.action=='SPEAKING':
            if len(self.controls)!=math.ceil(self.duration*PRESETS[self.quality]['fps']):
                raise ValueError('Speech controls must match duration and quality frame rate')
        elif self.controls or not 1<=self.duration<=5:
            raise ValueError('Expression/idle clips must be 1–5 seconds without speech controls')
        return self


def result_with_url(job):
    result=dict(job)
    if job['action']=='ATLAS' and job.get('partial_ready') and result['state']!='READY':
        # Core poses are done: the avatar can be used while the rest are rendered.
        result['partial_atlas_url']=f"/avatar/{job['avatar_id']}/neural/atlas/{job['cache_key']}?partial=1"
    if result['state']=='READY':
        if job['action']=='ATLAS':
            result['atlas_url']=f"/avatar/{job['avatar_id']}/neural/atlas/{job['cache_key']}"
        else:
            result['video_url']=f"/avatar/{job['avatar_id']}/neural/cache/{job['cache_key']}"
    return result


@router.post('/avatar/{avatar_id}/neural/atlas')
def start_atlas(avatar_id:str):
    metadata,image=read_avatar(avatar_id,UPLOADS,AVATAR_DATA)
    if not metadata.get('animation_available'):
        raise HTTPException(409,'A portrait with usable facial regions is required.')
    from ..avatar_library import prepared_atlas
    key=prepared_atlas(metadata)
    if key:
        # A ready-made avatar (avtars/): its poses were prepared on a PC — no engine needed.
        return result_with_url({'job_id':'library','avatar_id':avatar_id,'state':'READY','progress':1,'cached':True,
                                'cache_key':key,'quality':'balanced','action':'ATLAS','playback_mode':'CACHED POSES'})
    try:
        return result_with_url(manager.start(avatar_id,image,metadata,AVATAR_DATA/avatar_id/'neural','ATLAS','balanced',duration=1))
    except RuntimeError as error:
        raise HTTPException(429 if 'busy' in str(error) else 503,str(error))
    except (OSError,ValueError):
        raise HTTPException(503,'Local neural model files are unavailable.')


def atlas_file(key,partial,suffix):
    if not re.fullmatch('[a-f0-9]{64}',key):raise HTTPException(400,'Invalid atlas key.')
    path=AVATAR_DATA/'neural_atlases'/f"{key}{'.partial' if partial else ''}{suffix}"
    if not path.is_file():raise HTTPException(404,'Prepared avatar expired. Prepare it again.')
    return path


@router.get('/avatar/{avatar_id}/neural/atlas/{key}')
def atlas_manifest(avatar_id:str,key:str,partial:bool=False):
    import json
    read_avatar(avatar_id,UPLOADS,AVATAR_DATA)
    details=json.loads(atlas_file(key,partial,'.json').read_text(encoding='utf-8'))
    details['image_url']=f"/avatar/{avatar_id}/neural/atlas/{key}/image{'?partial=1' if partial else ''}"
    return details


@router.get('/avatar/{avatar_id}/neural/atlas/{key}/image')
def atlas_image(avatar_id:str,key:str,partial:bool=False):
    read_avatar(avatar_id,UPLOADS,AVATAR_DATA)
    # The partial image is replaced by the full one minutes later: never cache it.
    return FileResponse(atlas_file(key,partial,'.png'),media_type='image/png',
                        headers={'Cache-Control':'no-store' if partial else 'private, max-age=3600'})


@router.post('/avatar/{avatar_id}/neural/jobs')
def start_neural(avatar_id:str,body:NeuralRequest):
    metadata,image=read_avatar(avatar_id,UPLOADS,AVATAR_DATA)
    if not metadata.get('animation_available'):
        raise HTTPException(409,'A portrait with usable facial regions is required.')
    try:
        result=manager.start(avatar_id,image,metadata,AVATAR_DATA/avatar_id/'neural',body.action,body.quality,
                             [point.model_dump() for point in body.controls],body.duration)
        return result_with_url(result)
    except RuntimeError as error:
        raise HTTPException(429 if 'busy' in str(error) else 503,str(error))
    except (OSError,ValueError):
        raise HTTPException(503,'Optional local neural model files are unavailable.')


@router.get('/avatar/{avatar_id}/neural/jobs/{job_id}')
def neural_status(avatar_id:str,job_id:str):
    read_avatar(avatar_id,UPLOADS,AVATAR_DATA)
    try:return result_with_url(manager.status(job_id,avatar_id))
    except KeyError:raise HTTPException(404,'Neural job not found.')


@router.post('/avatar/{avatar_id}/neural/jobs/{job_id}/cancel')
def cancel_neural(avatar_id:str,job_id:str):
    read_avatar(avatar_id,UPLOADS,AVATAR_DATA)
    try:return result_with_url(manager.cancel(job_id,avatar_id))
    except KeyError:raise HTTPException(404,'Neural job not found.')


@router.get('/avatar/{avatar_id}/neural/cache/{key}')
def neural_video(avatar_id:str,key:str):
    read_avatar(avatar_id,UPLOADS,AVATAR_DATA)
    if not re.fullmatch('[a-f0-9]{64}',key):raise HTTPException(400,'Invalid cache key.')
    path=AVATAR_DATA/avatar_id/'neural'/'cache'/f'{key}.mp4'
    if not path.is_file():raise HTTPException(404,'Neural video cache expired.')
    return FileResponse(path,media_type='video/mp4',headers={'Cache-Control':'private, max-age=3600'})
