"""Inspected official LivePortrait modules, evaluated only with CPU tensors.
The optional worker environment owns torch; the FastAPI process does not import it.
"""
import gc
import hashlib
import json
from pathlib import Path
import sys
import time
from .base_engine import NeuralAvatarEngine, MotionControl
from .preprocessor import prepare_image, paste_frame
from ...vendor.liveportrait.expression import (
    update_delta_new_eyeball_direction, update_delta_new_smile,
    update_delta_new_lip_variation_one, update_delta_new_lip_variation_two,
    update_delta_new_lip_variation_three, update_delta_new_eyebrow,
)

ROOT=Path(__file__).resolve().parents[4]
RUNTIME=ROOT/'.tools'/'neural-evaluation'


class LivePortraitCPU(NeuralAvatarEngine):
    def __init__(self):
        self.models={}
        self.info={}

    def load(self):
        if self.models:
            return self.info
        import torch
        import yaml
        import psutil
        if torch.version.cuda is not None:
            raise RuntimeError('This installation requires the CPU-only PyTorch wheel')
        torch.set_num_threads(2)
        try:torch.set_num_interop_threads(1)
        except RuntimeError:pass  # The process may be reloading an unloaded model.
        from ...vendor.liveportrait.modules.appearance_feature_extractor import AppearanceFeatureExtractor
        from ...vendor.liveportrait.modules.motion_extractor import MotionExtractor
        from ...vendor.liveportrait.modules.warping_network import WarpingNetwork
        from ...vendor.liveportrait.modules.spade_generator import SPADEDecoder
        from ...vendor.liveportrait.camera import headpose_pred_to_degree,get_rotation_matrix
        self.torch=torch;self.degree=headpose_pred_to_degree;self.rotation=get_rotation_matrix
        config=yaml.safe_load((RUNTIME/'models.yaml').read_text())['model_params']
        manifest=json.loads((RUNTIME/'weights.json').read_text())
        started=time.perf_counter()
        for item in manifest:
            path=RUNTIME/'weights'/Path(item['path']).name
            with path.open('rb') as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=item['lfs']['oid']:
                    raise ValueError('Model checksum mismatch: '+path.name)
        classes=[('appearance_feature_extractor',AppearanceFeatureExtractor,'appearance_feature_extractor_params'),
                 ('motion_extractor',MotionExtractor,'motion_extractor_params'),
                 ('warping_module',WarpingNetwork,'warping_module_params'),
                 ('spade_generator',SPADEDecoder,'spade_generator_params')]
        for name,cls,key in classes:
            model=cls(**config[key]).to('cpu').eval()
            weights=torch.load(RUNTIME/'weights'/f'{name}.pth',map_location='cpu',weights_only=True)
            model.load_state_dict(weights,strict=True)
            del weights
            self.models[name]=model
        self.info={'model':'LivePortrait','device':'cpu','runtime':torch.__version__,
                   'load_seconds':time.perf_counter()-started,'model_bytes':sum(i['size'] for i in manifest),
                   'rss_bytes':psutil.Process().memory_info().rss,
                   'revision':(RUNTIME/'revision.txt').read_text().strip()}
        return self.info

    def prepare_avatar(self,image_path,metadata,cache_dir,resolution):
        import numpy as np
        torch=self.torch
        started=time.perf_counter()
        state,key,cached=prepare_image(image_path,metadata,cache_dir)
        cache=cache_dir/f'features-{resolution}.npz'
        cache_key=key+str(resolution)+self.info['revision']
        arrays=None
        if cache.exists():
            try:
                with np.load(cache,allow_pickle=False) as data:
                    if str(data['key'])==cache_key:arrays={name:data[name].copy() for name in data.files if name!='key'}
            except (OSError,ValueError,KeyError):pass
        with torch.inference_mode():
            if arrays is None:
                tensor=torch.from_numpy(state['crop'].transpose(2,0,1).copy()).float().unsqueeze(0)/255
                feature=self.models['appearance_feature_extractor'](torch.nn.functional.interpolate(tensor,size=(resolution,resolution),mode='bilinear',align_corners=False))
                info=self.models['motion_extractor'](tensor)
                for name in ['pitch','yaw','roll']:info[name]=self.degree(info[name]).reshape(1,1)
                info['kp']=info['kp'].reshape(1,-1,3);info['exp']=info['exp'].reshape(1,-1,3)
                arrays={name:value.numpy() for name,value in info.items()};arrays['feature']=feature.numpy()
                pending=cache.with_suffix('.pending.npz')
                np.savez_compressed(pending,key=np.array(cache_key),**arrays);pending.replace(cache)
            state['tensors']={name:torch.from_numpy(value) for name,value in arrays.items()}
            info=state['tensors']
            state['source']=info['scale'].reshape(1,1,1)*(info['kp']@self.rotation(info['pitch'],info['yaw'],info['roll'])+info['exp'])
            state['source'][:,:,:2]+=info['t'][:,:2].reshape(1,1,2)
        state['prepare_seconds']=time.perf_counter()-started
        return state

    def render(self,prepared,control:MotionControl):
        import numpy as np
        torch=self.torch;info=prepared['tensors']
        with torch.inference_mode():
            exp=info['exp'].clone()
            blink=float(np.clip(control.blink,0,1))
            for index in [11,15]:exp[0,index,1]+=.027*blink
            for index in [13,16]:exp[0,index,1]-=.0081*blink
            smile=float(np.clip(control.smile,-.1,1.))
            update_delta_new_smile(smile, exp)
            update_delta_new_eyeball_direction(float(np.clip(control.gaze_x,-8,8)), float(np.clip(control.gaze_y,-8,8)), exp)
            update_delta_new_eyebrow(float(np.clip(control.eyebrow,-20,20)), exp)
            opening=float(np.clip(control.mouth_open,0,.75))
            update_delta_new_lip_variation_three(60*opening, exp)
            # Rounding uses the upstream depth/vertical lip control; moving
            # point 19 sideways produced an asymmetric mouth instead.
            update_delta_new_lip_variation_two(8*float(np.clip(control.lip_roundness,0,1))*opening, exp)
            width=float(np.clip(control.mouth_width,.75,1.15))-1
            update_delta_new_lip_variation_one(-10*width, exp)
            update_delta_new_lip_variation_two(20*width, exp)
            rotation=self.rotation(info['pitch']+float(np.clip(control.pitch,-2,2)),info['yaw']+float(np.clip(control.yaw,-3,3)),info['roll'])
            driving=info['scale'].reshape(1,1,1)*(info['kp']@rotation+exp)
            driving[:,:,:2]+=info['t'][:,:2].reshape(1,1,2)
            warped=self.models['warping_module'](info['feature'],kp_driving=driving,kp_source=prepared['source'])
            output=self.models['spade_generator'](warped['out'])
            if not torch.isfinite(output).all():raise ValueError('Non-finite neural inference')
            rgb=(output[0].permute(1,2,0).clamp(0,1).numpy()*255).astype(np.uint8)
        return paste_frame(rgb,prepared,mouth_only=control.mouth_only)

    def unload(self):
        self.models.clear();gc.collect()
