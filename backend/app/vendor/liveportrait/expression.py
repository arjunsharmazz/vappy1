"""Expression math extracted from LivePortrait src/gradio_pipeline.py.
MIT, Copyright (c) 2024 Kuaishou Visual Generation and Interaction Center.
Revision: 9b294b3d0536135442ea73cb01e6cb3ca7029dd3.
Changes: remove Gradio class/self and torch decorator; caller owns inference mode.
See THIRD_PARTY_NOTICES.md and vendor/licenses/LivePortrait.txt.
"""

def update_delta_new_eyeball_direction(eyeball_direction_x, eyeball_direction_y, delta_new, **kwargs):
    if eyeball_direction_x > 0:
        delta_new[0, 11, 0] += eyeball_direction_x * 0.0007
        delta_new[0, 15, 0] += eyeball_direction_x * 0.001
    else:
        delta_new[0, 11, 0] += eyeball_direction_x * 0.001
        delta_new[0, 15, 0] += eyeball_direction_x * 0.0007
    delta_new[0, 11, 1] += eyeball_direction_y * -0.001
    delta_new[0, 15, 1] += eyeball_direction_y * -0.001
    blink = -eyeball_direction_y / 2.0
    delta_new[0, 11, 1] += blink * -0.001
    delta_new[0, 13, 1] += blink * 0.0003
    delta_new[0, 15, 1] += blink * -0.001
    delta_new[0, 16, 1] += blink * 0.0003
    return delta_new

def update_delta_new_smile(smile, delta_new, **kwargs):
    delta_new[0, 20, 1] += smile * -0.01
    delta_new[0, 14, 1] += smile * -0.02
    delta_new[0, 17, 1] += smile * 0.0065
    delta_new[0, 17, 2] += smile * 0.003
    delta_new[0, 13, 1] += smile * -0.00275
    delta_new[0, 16, 1] += smile * -0.00275
    delta_new[0, 3, 1] += smile * -0.0035
    delta_new[0, 7, 1] += smile * -0.0035
    return delta_new

def update_delta_new_lip_variation_one(lip_variation_one, delta_new, **kwargs):
    delta_new[0, 14, 1] += lip_variation_one * 0.001
    delta_new[0, 3, 1] += lip_variation_one * -0.0005
    delta_new[0, 7, 1] += lip_variation_one * -0.0005
    delta_new[0, 17, 2] += lip_variation_one * -0.0005
    return delta_new

def update_delta_new_lip_variation_two(lip_variation_two, delta_new, **kwargs):
    delta_new[0, 20, 2] += lip_variation_two * -0.001
    delta_new[0, 20, 1] += lip_variation_two * -0.001
    delta_new[0, 14, 1] += lip_variation_two * -0.001
    return delta_new

def update_delta_new_lip_variation_three(lip_variation_three, delta_new, **kwargs):
    delta_new[0, 19, 1] += lip_variation_three * 0.001
    delta_new[0, 19, 2] += lip_variation_three * 0.0001
    delta_new[0, 17, 1] += lip_variation_three * -0.0001
    return delta_new

def update_delta_new_eyebrow(eyebrow, delta_new, **kwargs):
    if eyebrow > 0:
        delta_new[0, 1, 1] += eyebrow * 0.001
        delta_new[0, 2, 1] += eyebrow * -0.001
    else:
        delta_new[0, 1, 0] += eyebrow * -0.001
        delta_new[0, 2, 0] += eyebrow * 0.001
        delta_new[0, 1, 1] += eyebrow * 0.0003
        delta_new[0, 2, 1] += eyebrow * -0.0003
    return delta_new
