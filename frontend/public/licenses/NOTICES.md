# Selected upstream components

The three official repositories were shallow-cloned into `third_party/`. Their full applications are not merged into the FastAPI environment. Only the components listed here run in this app. No SadTalker or MuseTalk model weights were downloaded.

| Repository | Pinned commit | Integrated component | Local destination |
| --- | --- | --- | --- |
| [SadTalker](https://github.com/OpenTalker/SadTalker) | `cd4c0465ae0b54a6f85af57f5c65fec9fe23e7f8` | Five-sample blink closure profile from `src/generate_batch.py`, with smooth interpolation and zero endpoints; existing 180 ms duration and random scheduling retained | `frontend/src/animation/blinkProfile.js`, used by `PortraitEngine.js` |
| [MuseTalk](https://github.com/TMElyralab/MuseTalk) | `0a89dec45a0192b824e3cf4daf96c239440c5ed8` | Cached soft mask, lower-face boundary and Gaussian feathering from `musetalk/utils/blending.py`; adapted to saved face regions and NumPy/OpenCV | `backend/app/services/neural_avatar/blending.py`, used by `preprocessor.py` and neural frame output |
| [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) | `9b294b3d0536135442ea73cb01e6cb3ca7029dd3` | Appearance and motion extraction, dense motion, warping, SPADE decoding, ConvNeXtV2 helpers, head-pose transforms | `backend/app/vendor/liveportrait/`, loaded by `model_loader.py` in the isolated CPU worker |

LivePortrait's seven selected `src/modules/*.py` files and `src/utils/camera.py` are copied without code changes. The wrapper supplies existing validated local weights, CPU tensors, bounded controls, source-feature caching and failure checks. Neural speech clips use the lower-face mask; full-expression previews use the face mask. The face mask uses existing approximate face regions, **not** MuseTalk's learned face parser.

The SadTalker adaptation changes timing interpolation, not neural audio-to-motion inference. The MuseTalk adaptation is a compositor, not the MuseTalk diffusion lip-sync model. This app does not claim to run either full model. LivePortrait performs actual neural inference, exposed as explicit pre-rendered previews because measured CPU speed is too slow for live conversation. Live voice uses the existing Lightweight renderer.

License texts are retained under `backend/app/vendor/licenses/`:

- `SadTalker.txt`: Apache License 2.0. The JavaScript adaptation is identified above and in its source header.
- `MuseTalk.txt`: MIT, Copyright (c) 2024 Tencent Music Entertainment Group; includes upstream's dependency notices.
- `LivePortrait.txt`: MIT, Copyright (c) 2024 Kuaishou Visual Generation and Interaction Center; includes upstream's third-party notices.

The complete licenses are also copied to `frontend/public/licenses/` for frontend distribution. Model licenses and upstream dependency terms remain distinct from these application-code licenses. The app does not load upstream face recognition packages or animal models.

To reproduce the inspected checkouts, from the project root:

```powershell
git clone --depth 1 https://github.com/OpenTalker/SadTalker.git third_party/SadTalker
git clone --depth 1 https://github.com/TMElyralab/MuseTalk.git third_party/MuseTalk
git clone --depth 1 https://github.com/KlingAIResearch/LivePortrait.git third_party/LivePortrait
```

Those commands track current upstream HEAD. The integrated snapshots are identified by the pinned commits above; review upstream changes before updating vendored code.
