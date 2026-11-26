"""Local CPU feasibility gate. Run with .tools/neural-venv/Scripts/python.exe.
No model download occurs here. Requires inspected upstream modules/verified weights.
"""
import argparse
import gc
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / '.tools' / 'neural-evaluation'
sys.path.insert(0, str(EVAL / 'liveportrait'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--avatar', default='158d62a4-0419-4af5-a3f1-24a6059efd8f')
    parser.add_argument('--frames', type=int, default=1)
    parser.add_argument('--fps', type=int, default=4)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--resolution', type=int, choices=[128,256], default=256)
    parser.add_argument('--control', choices=['rest','blink','smile','head'], default='rest')
    args = parser.parse_args()
    if not 1 <= args.frames <= 120 or not 1 <= args.fps <= 24:
        raise ValueError('Bounded benchmark: 1..120 frames, 1..24 FPS')
    import cv2
    import numpy as np
    import psutil
    import torch
    import yaml
    from modules.appearance_feature_extractor import AppearanceFeatureExtractor
    from modules.motion_extractor import MotionExtractor
    from modules.warping_network import WarpingNetwork
    from modules.spade_generator import SPADEDecoder
    from camera import headpose_pred_to_degree, get_rotation_matrix
    if torch.version.cuda is not None:raise RuntimeError('CPU-only PyTorch is required')
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    cv2.setNumThreads(1)
    process = psutil.Process()
    stopped = threading.Event()
    peak = [process.memory_info().rss]
    def monitor():
        while not stopped.wait(.1):
            peak[0] = max(peak[0], process.memory_info().rss)
    threading.Thread(target=monitor, daemon=True).start()
    result = {'model':'LivePortrait official human models', 'source_revision':(EVAL/'revision.txt').read_text().strip(),
              'device':'cpu', 'torch':torch.__version__, 'cuda_runtime':torch.version.cuda,
              'threads':args.threads, 'internal_resolution':args.resolution, 'control':args.control, 'requested_frames':args.frames, 'output_fps':args.fps,
              'model_bytes':sum(p.stat().st_size for p in (EVAL/'weights').glob('*.pth'))}
    out = EVAL / 'benchmark-output'; out.mkdir(exist_ok=True)
    try:
        config = yaml.safe_load((EVAL/'models.yaml').read_text())['model_params']
        started = time.perf_counter()
        models = {}
        for name, cls, config_name in [
            ('appearance_feature_extractor',AppearanceFeatureExtractor,'appearance_feature_extractor_params'),
            ('motion_extractor',MotionExtractor,'motion_extractor_params'),
            ('warping_module',WarpingNetwork,'warping_module_params'),
            ('spade_generator',SPADEDecoder,'spade_generator_params')]:
            model = cls(**config[config_name]).to('cpu').eval()
            weights = torch.load(EVAL/'weights'/f'{name}.pth', map_location='cpu', weights_only=True)
            model.load_state_dict(weights, strict=True)
            del weights
            models[name] = model
            print('Loaded',name,round(time.perf_counter()-started,3),'seconds',flush=True)
        result['model_load_seconds'] = time.perf_counter()-started
        record_path = ROOT/'avatar_data'/args.avatar/'avatar.json'
        record = json.loads(record_path.read_text())
        image = cv2.imread(str(record_path.parent/'original.jpg'))
        face = record['face_box']; left=record['landmarks']['left_eye'];right=record['landmarks']['right_eye']
        started=time.perf_counter()
        angle=np.degrees(np.arctan2(right['y']-left['y'],right['x']-left['x']))
        center=((left['x']+right['x'])/2,(left['y']+right['y'])/2)
        transform=cv2.getRotationMatrix2D(center,angle,256/(face['width']*1.45))
        transform[:,2]+=np.array([128,100])-np.array(center)
        crop=cv2.warpAffine(image,transform,(256,256),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        cv2.imwrite(str(out/'source-crop.png'),crop)
        tensor=torch.from_numpy(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB).transpose(2,0,1).copy()).float().unsqueeze(0)/255
        with torch.inference_mode():
            features=models['appearance_feature_extractor'](torch.nn.functional.interpolate(tensor,size=(args.resolution,args.resolution),mode='bilinear',align_corners=False))
            info=models['motion_extractor'](tensor)
            for name in ['pitch','yaw','roll']:info[name]=headpose_pred_to_degree(info[name]).reshape(1,1)
            kp=info['kp'].reshape(1,-1,3);exp=info['exp'].reshape(1,-1,3)
            rotation=get_rotation_matrix(info['pitch'],info['yaw'],info['roll'])
            source=info['scale'].reshape(1,1,1)*(kp@rotation+exp)
            source[:,:,:2]+=info['t'][:,:2].reshape(1,1,2)
            result['preprocessing_seconds']=time.perf_counter()-started
            print('Prepared source',result['preprocessing_seconds'],'seconds',flush=True)
            times=[];inference_times=[];generation_start=time.perf_counter()
            for i in range(args.frames):
                start=time.perf_counter()
                # Tiny actual model-space head rotation, source identity features cached.
                delta=(1.5 if args.frames==1 else 1.5*np.sin(2*np.pi*i/max(1,args.frames-1))) if args.control=='head' else 0
                driving_rotation=get_rotation_matrix(info['pitch'],info['yaw']+delta,info['roll'])
                expression=exp.clone()
                amount=1 if args.frames==1 else np.sin(np.pi*i/max(1,args.frames-1))**2
                if args.control=='blink':
                    for lid in [11,15]:expression[0,lid,1]+=.027*amount
                    for lid in [13,16]:expression[0,lid,1]-=.0081*amount
                if args.control=='smile':
                    for point,axis,offset in [(20,1,-.01),(14,1,-.02),(17,1,.0065),(17,2,.003),(13,1,-.00275),(16,1,-.00275),(3,1,-.0035),(7,1,-.0035)]:expression[0,point,axis]+=offset*.55*amount
                driving=info['scale'].reshape(1,1,1)*(kp@driving_rotation+expression)
                driving[:,:,:2]+=info['t'][:,:2].reshape(1,1,2)
                warped=models['warping_module'](features,kp_driving=driving,kp_source=source)
                prediction=models['spade_generator'](warped['out'])
                if not torch.isfinite(prediction).all():raise ValueError('Non-finite neural output')
                rgb=(prediction[0].permute(1,2,0).clamp(0,1).numpy()*255).astype(np.uint8)
                if rgb.std()<3:raise ValueError('Corrupted flat neural output')
                inference_times.append(time.perf_counter()-start)
                cv2.imwrite(str(out/f'frame-{i:04d}.png'),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))
                times.append(time.perf_counter()-start)
                del warped,prediction,rgb
                if process.memory_info().rss>10*1024**3:raise MemoryError('Evaluation exceeded 10 GiB RAM limit')
                print('Frame',i+1,'/',args.frames,round(times[-1],3),'seconds',flush=True)
            result.update(single_frame_seconds=inference_times[0],mean_frame_seconds=float(np.mean(inference_times)),
                          approximate_inference_fps=1/float(np.mean(inference_times)),inference_seconds=inference_times,frame_with_png_seconds=times,
                          measured_generation_seconds=time.perf_counter()-generation_start,
                          generated_animation_seconds=args.frames/args.fps,
                          ten_second_generation_seconds=(time.perf_counter()-generation_start) if args.frames/args.fps==10 else None)
        result['status']='measured'
    except Exception as error:
        result['status']='failed';result['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        stopped.set();result['peak_process_rss_bytes']=peak[0];result['final_process_rss_bytes']=process.memory_info().rss
        (EVAL/'benchmark_results.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
