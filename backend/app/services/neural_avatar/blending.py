"""CPU mask preparation adapted from MuseTalk get_image_prepare_material.

MIT, Copyright (c) 2024 Tencent Music Entertainment Group.
See THIRD_PARTY_NOTICES.md and backend/app/vendor/licenses/MuseTalk.txt.
Changes: accepts the app's existing face mask instead of a neural face parser;
works directly in source coordinates and clamps to the original support, so
background pixels remain exactly unchanged. Precomputed once per portrait.
"""
import cv2
import numpy as np


def prepare_blend_mask(face_mask, face_box, lower_face=False):
    mask = np.asarray(face_mask, dtype=np.float32).copy()
    if lower_face:
        boundary = int(face_box['y'] + face_box['height'] * .50)
        mask[:max(0, boundary)] = 0
    kernel = max(3, int(.05 * face_box['width']) // 2 * 2 + 1)
    blurred = cv2.GaussianBlur(mask, (kernel, kernel), 0)
    return np.minimum(np.clip(blurred, 0, 1), face_mask).astype(np.float32)


def composite(source, generated, mask):
    alpha = mask[..., None]
    return np.rint(generated.astype(np.float32) * alpha + source.astype(np.float32) * (1 - alpha)).clip(0, 255).astype(np.uint8)
