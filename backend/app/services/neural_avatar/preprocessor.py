"""One-time alignment from the application's saved face/eye regions."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from .blending import prepare_blend_mask, composite

VERSION = 2


def prepare_image(image_path: Path, metadata: dict, cache_dir: Path):
    fingerprint = hashlib.sha256(image_path.read_bytes()).hexdigest()
    key = hashlib.sha256(json.dumps({'version': VERSION, 'image': fingerprint,
        'face': metadata['face_box'], 'landmarks': metadata['landmarks']}, sort_keys=True).encode()).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / 'alignment.npz'
    if cached.is_file():
        try:
            with np.load(cached, allow_pickle=False) as state:
                if str(state['key']) == key:
                    return {name:state[name].copy() for name in ['image','crop','matrix','mask','mouth_mask']}, key, True
        except (ValueError, OSError, KeyError):
            pass
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError('Original portrait cannot be decoded')
    face = metadata['face_box']; left = metadata['landmarks']['left_eye']; right = metadata['landmarks']['right_eye']
    center = ((left['x']+right['x'])/2, (left['y']+right['y'])/2)
    angle = np.degrees(np.arctan2(right['y']-left['y'], right['x']-left['x']))
    matrix = cv2.getRotationMatrix2D(center, angle, 256/(face['width']*1.45))
    matrix[:,2] += np.array([128,100])-np.array(center)
    image = cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
    crop = cv2.warpAffine(image,matrix,(256,256),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
    # Leave exterior/background pixels EXACTLY original. Changes are restricted
    # to a soft face ellipse, not a rectangular crop or whole-image transform.
    y,x = np.mgrid[:image.shape[0],:image.shape[1]]
    nx=(x-face['x']-face['width']*.5)/(face['width']*.49)
    ny=(y-face['y']-face['height']*.51)/(face['height']*.49)
    inside=np.clip((1-nx*nx-ny*ny)/.30,0,1)
    mask=(inside*inside*(3-2*inside)).astype(np.float32)
    state={'image':image,'crop':crop,'matrix':matrix,
           'mask':prepare_blend_mask(mask,face), 'mouth_mask':prepare_blend_mask(mask,face,lower_face=True)}
    pending=cache_dir/'alignment.pending.npz'
    np.savez_compressed(pending,key=np.array(key),**state)
    pending.replace(cached)
    return state,key,False


def paste_frame(rgb, prepared, mouth_only=False):
    if rgb.ndim!=3 or rgb.shape[2]!=3 or not np.isfinite(rgb).all() or rgb.std()<3:
        raise ValueError('Corrupted neural frame')
    source=prepared['image'];matrix=prepared['matrix'].copy()
    matrix*=rgb.shape[0]/256
    warp=cv2.warpAffine(rgb,cv2.invertAffineTransform(matrix),(source.shape[1],source.shape[0]),flags=cv2.INTER_LINEAR)
    mask=prepared.get('mouth_mask',prepared['mask']) if mouth_only else prepared['mask']
    selected=prepared['mask']>.8
    if selected.any() and np.abs(warp[selected].astype(float)-source[selected]).mean()>85:
        raise ValueError('Neural frame differs excessively from source; use Lightweight mode')
    return composite(source,warp,mask)
