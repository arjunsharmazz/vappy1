"""Prepare bounded neural poses once for local audio-driven browser playback."""
import json
from pathlib import Path
import time
import cv2
import numpy as np
from .base_engine import MotionControl

ATLAS_VERSION = 5
# v5: poses are rendered most-important first. After CORE_POSES the avatar is already usable
# (talks, blinks, looks at you) and a partial atlas is published; the rest follow in the
# background. Fewer in-between steps than v4 (blink 8→4, round/wide 4→3): the browser blends
# between neighbours, and a 180 ms blink needs only a few lid positions. Existing v4 tiles with
# the same (kind, value) are reused, so already prepared faces are not rendered again.
# ~17 s per pose on an i5-4300U, so the core is kept to what talking needs: one open mouth (the
# browser blends from the closed photo), closed eyes, and left/right eye contact (~75 s).
CORE_POSES = 4
POSES = [
    ('mouth', .45, MotionControl(mouth_open=.45, mouth_only=True)),
    ('blink', 1., MotionControl(blink=1.)),
    ('left', 1., MotionControl(gaze_x=-6)), ('right', 1., MotionControl(gaze_x=6)),
    ('mouth', .30, MotionControl(mouth_open=.30, mouth_only=True)),
    ('mouth', .60, MotionControl(mouth_open=.60, mouth_only=True)),
    ('blink', .5, MotionControl(blink=.5)),
] + [('mouth', value, MotionControl(mouth_open=value, mouth_only=True)) for value in [.15, .75]] + [
    ('round', value, MotionControl(mouth_open=value, mouth_width=.8, lip_roundness=1, mouth_only=True))
    for value in [.15, .30, .60]
] + [
    ('wide', value, MotionControl(mouth_open=value, mouth_width=1.12, mouth_only=True))
    for value in [.15, .30, .60]
] + [('blink', value, MotionControl(blink=value)) for value in [.25, .75]] + [
    # v4 expressions. Values were chosen from rendered contact sheets of a real portrait:
    # smile 1.0 lifts the cheeks and creases the eyes (0.6 only moved the lips);
    # a laugh is that smile with an opening mouth (above .45 the smile is lost).
    ('happy', .5, MotionControl(smile=.5)), ('happy', 1., MotionControl(smile=1.)),
] + [('laugh', value, MotionControl(smile=1., mouth_open=value, blink=.12)) for value in [.15, .30, .45]] + [
    ('brow', 6., MotionControl(eyebrow=6)), ('brow', 12., MotionControl(eyebrow=12)),
    ('frown', 8., MotionControl(eyebrow=-8)),
    # Vertical gaze for camera-driven eye contact (horizontal reuses left/right).
    ('up', 1., MotionControl(gaze_y=5)), ('down', 1., MotionControl(gaze_y=-4)),
]


def _save(atlas, details, output):
    output = Path(output); pending = output.with_suffix('.pending.png')
    manifest = output.with_suffix('.json'); pending_manifest = manifest.with_suffix('.pending.json')
    try:
        if not cv2.imwrite(str(pending), cv2.cvtColor(atlas, cv2.COLOR_RGBA2BGRA)):
            raise OSError('Could not save neural poses')
        pending_manifest.write_text(json.dumps(details), encoding='utf-8')
        pending.replace(output); pending_manifest.replace(manifest)
    finally:
        pending.unlink(missing_ok=True); pending_manifest.unlink(missing_ok=True)


def partial_path(output):
    output = Path(output)
    return output.with_name(output.stem + '.partial.png')


def generate_atlas(engine, prepared, metadata, output, check, progress, reuse_path=None, partial=None):
    started = time.perf_counter()
    source = prepared['image']; height, width = source.shape[:2]
    face = metadata['face_box']; landmarks = metadata['landmarks']
    x = max(0, int(face['x'] - .08 * face['width']))
    y = max(0, int(face['y'] - .08 * face['height']))
    right = min(width, int(face['x'] + 1.08 * face['width']))
    bottom = min(height, int(face['y'] + 1.12 * face['height']))
    tile = 512; columns = 4
    rows = (len(POSES) + 1 + columns - 1) // columns
    atlas = np.zeros((rows * tile, columns * tile, 4), np.uint8)
    rect = {'x':x,'y':y,'width':right-x,'height':bottom-y}
    reusable = {}
    if reuse_path:
        try:
            old = json.loads(Path(reuse_path).with_suffix('.json').read_text(encoding='utf-8'))
            old_image = cv2.imread(str(reuse_path),cv2.IMREAD_UNCHANGED)
            if old['version'] in [1,2,3,4,5] and old['rect']==rect and old['tile']==tile and old_image is not None and old_image.shape[2]==4:
                old_image=cv2.cvtColor(old_image,cv2.COLOR_BGRA2RGBA)
                for entry in old['entries']:
                    row,col=divmod(entry['index'],old['columns'])
                    patch=old_image[row*tile:(row+1)*tile,col*tile:(col+1)*tile]
                    if patch.shape==(tile,tile,4): reusable[(entry['kind'],entry['value'])]=patch.copy()
        except (OSError,ValueError,KeyError,IndexError,cv2.error):
            reusable={}
    yy, xx = np.mgrid[:height, :width]
    eye_mask = np.zeros((height, width), np.float32)
    for name in ['left_eye', 'right_eye']:
        eye = landmarks[name]
        radius = ((xx-eye['x'])/(eye['width']*1.05))**2 + ((yy-eye['y'])/(eye['height']*1.35))**2
        weight = np.clip((1-radius)/.5, 0, 1)
        eye_mask = np.maximum(eye_mask, weight*weight*(3-2*weight))
    mouth_mask = prepared['mouth_mask']
    # Mouth expressions cannot change the nose or the upper face.
    mouth = landmarks['mouth']
    ramp = np.clip((yy-(mouth['y']-mouth['height']*.8))/(mouth['height']*.5), 0, 1)
    mouth_mask = mouth_mask * ramp*ramp*(3-2*ramp)
    # Eyebrows: a band above each eye plus the space between the brows (frown lines).
    # It stops just above the eye centre so a raised brow never ghosts the iris.
    brow_mask = np.zeros((height, width), np.float32)
    left, right_eye = landmarks['left_eye'], landmarks['right_eye']
    gap = abs(right_eye['x'] - left['x'])
    regions = [(e['x'], e['y'] - e['height'] * 1.45, e['width'] * 1.15, e['height'] * 1.25) for e in (left, right_eye)]
    regions.append(((left['x'] + right_eye['x']) / 2, (left['y'] + right_eye['y']) / 2 - left['height'] * 1.3,
                    gap * .32, left['height'] * 1.3))
    for cx, cy, rx, ry in regions:
        radius = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
        weight = np.clip((1 - radius) / .5, 0, 1)
        brow_mask = np.maximum(brow_mask, weight * weight * (3 - 2 * weight))
    # Smiles and laughs move cheeks and eye creases too, so they use the soft face mask.
    face_mask = prepared['mask']
    masks = {'mouth':mouth_mask,'round':mouth_mask,'wide':mouth_mask,
             'blink':eye_mask,'left':eye_mask,'right':eye_mask,'up':eye_mask,'down':eye_mask,
             'happy':face_mask,'laugh':face_mask,'brow':brow_mask,'frown':brow_mask}

    def put(index, image, mask):
        patch = np.dstack((image, np.rint(mask*255).astype(np.uint8)))[y:bottom,x:right]
        row, col = divmod(index, columns)
        atlas[row*tile:(row+1)*tile,col*tile:(col+1)*tile] = cv2.resize(patch,(tile,tile),interpolation=cv2.INTER_AREA)

    put(0, source, np.ones((height,width),np.float32))
    entries = [{'kind':'rest','value':0,'index':0}]
    reused=0
    for index, (kind, value, control) in enumerate(POSES, 1):
        check()
        if (kind,value) in reusable:
            row,col=divmod(index,columns)
            atlas[row*tile:(row+1)*tile,col*tile:(col+1)*tile]=reusable[(kind,value)]
            reused+=1
        else:
            frame = engine.render(prepared, control)
            check(); put(index, frame, masks[kind])
        entries.append({'kind':kind,'value':value,'index':index})
        progress(index, len(POSES))
        if index == CORE_POSES and partial is not None and index < len(POSES) and reused < index:
            # Usable already: publish the rows rendered so far; the rest continue below.
            used = (index + columns) // columns * tile
            _save(atlas[:used].copy(), {'version':ATLAS_VERSION,'tile':tile,'columns':columns,'entries':list(entries),
                  'rect':rect,'partial':True,'image_width':width,'image_height':height}, partial_path(output))
            partial()
    check()
    details = {'version':ATLAS_VERSION,'tile':tile,'columns':columns,'entries':entries,
               'rect':rect,'reused_poses':reused,
               'image_width':width,'image_height':height,'generation_seconds':time.perf_counter()-started}
    _save(atlas, details, output)
    for leftover in (partial_path(output), partial_path(output).with_suffix('.json')):
        leftover.unlink(missing_ok=True)
    return details
