# Phase 4 implementation and validation

Phase 4 extends the existing local renderer. It adds text-aware timing and secondary facial motion; it does not introduce a new TTS engine, cloud service, microphone, chatbot, model dependency or API endpoint.

## Files modified

- `frontend/src/animation/PortraitEngine.js`: orchestrates priority/queued expressions, independently completing blinks, expression easing, cached eyebrow/cheek/head masks, gaze, nods, adaptive frame pacing, breathing composition and development diagnostics.
- `frontend/src/animation/visemeEngine.js`: replaces the cyclic sequence with audio-clock timeline lookup; adds TH, I, L and S/Z; keeps amplitude-driven intensity and smooth transitions.
- `frontend/src/hooks/useAvatarSpeech.js`: builds spelling tokens before synthesis, fits their timeline after decoding and exposes playback time from AudioContext. Existing TTS requests, decoding, audio routing and cleanup are retained.
- `frontend/src/main.jsx`: permits expression buttons during speech so Smile/Laugh can queue.
- `frontend/tests/mouth.cjs`: covers all twelve visemes, text-driven timing, restoration and the expression/blink overlap regression.
- `README.md`: current rendering, controls, limitations and commands.

## Files created

- `frontend/src/animation/visemeTimeline.js`: approximate English character/digraph mapping, weighted duration allocation, punctuation pauses, one-time decoded PCM analysis and binary-search lookup.
- `frontend/src/animation/IdleBehaviorController.js`: occasional gaze, tilt, nod and eyebrow events, independent of mouth timing; no consecutive identical event type; four-second breathing cycle; reduced-motion/paused behavior.
- `frontend/src/animation/BreathingLayer.js`: cached, softly masked shoulder/upper-torso layer, only when enough image exists below the face.
- `frontend/tests/phase4.cjs`: text/timing checks, actual 20-second idle observation, expression checks, five real TTS/playback cycles and speaking-priority/restoration checks.
- `PHASE4_REPORT.md`: this report.

The production `frontend/dist` output was rebuilt. Test images and machine-readable results are under `.tools`.

## Performance impact

Measured on this machine: Intel Core i5-4300U at 1.90 GHz, four logical CPUs, 16 GB RAM, headless Chrome, a 465 x 350 portrait with a face patch capped at 280 pixels per side.

The successful 20-second Phase 4 run measured a median **60 FPS**, median **8.19 ms** smoothed rendering cost and 95th percentile **10.54 ms** smoothed cost. Maximum observed head rotation was **0.56 degrees**. These are browser rendering measurements, not CPU utilization or a guarantee for every portrait/browser workload. The checked-in test saves results to `.tools/phase4-results.json`.

The prior renderer targeted 24 FPS; the new scheduler targets 60, backs off to 30 above 12 ms moving-average render cost and returns to 60 below 9 ms. Higher frame frequency increases CPU work. Four extra float masks add at most about 1.25 MB at a 280 x 280 patch; a shoulder canvas adds image-dependent storage. No neural model or runtime dependency was added. Landmark/region calculation and shoulder masking happen once per avatar. PCM analysis happens once per utterance, using 10 ms bins and downsampled samples. No per-frame backend/OpenCV calls are made.

## Tests actually performed

- Backend: `.venv/Scripts/python.exe -m unittest discover -s tests -v`, from `backend`: **28 tests passed**. Speech unit tests mock synthesis where appropriate and validate WAV handling; real synthesis is covered separately below.
- Production frontend: `npm.cmd run build --prefix frontend`: **passed**.
- `node frontend/tests/mouth.cjs`: **passed** all twelve shapes, original-lip separation over opaque backing, no new pure-black or pure-white pixels, fully closed REST/M/B/P, hidden teeth on closure, immutable source, five repeated restore cycles, text-driven shape transitions and blink continuation across expression completion.
- `node frontend/tests/phase2.cjs`: **passed** Smile, Laugh, Blink, Look Left/Right, automatic blink, visibility pause/resume, fallback/error states, upload feedback, reduced-motion behavior and mobile layout.
- `node frontend/tests/phase3.cjs avatar_data/158d62a4-0419-4af5-a3f1-24a6059efd8f/original.jpg`: **passed** real Windows speech synthesis, WAV decoding, active browser audio, measured amplitude, different mouth shapes, teeth visibility, blinking during speech, end/Stop cleanup, repeat playback, synthesis-error retry, cancellation, corrupt-audio recovery, blink intervals and mobile layout.
- `node frontend/tests/phase4.cjs`: **passed** the Hello spelling pattern (OPEN/E/L/O), fitted/ordered timelines, motion limits, paused secondary motion, 20 seconds of actual idle frames showing blink/gaze/head/breathing, coordinated Smile/Laugh and five real speech cycles using: “Hello! My name is AI Living Frame. It is nice to meet you.” The test also queues Smile during speech, checks it starts after playback, verifies jaw activity and compares settled paused-rest pixels after each cycle (one-level rasterization tolerance).
- Visually inspected the rendered viseme sheet, debug overlay and Laugh screenshot. Artifacts include `.tools/viseme-sheet.png`, `.tools/phase4-debug.png`, `.tools/phase4-smile.png`, `.tools/phase4-laugh.png` and `.tools/phase4-results.json`.

An initial Phase 4 test selector did not account for the icon in the Smile button's accessible name; corrected the test. Its first restoration comparison also sampled the expression while it was still easing; it now waits for fully settled neutral frames, and the five-cycle run passes. A separate blink-lifecycle edge case was fixed and regression-tested.

## Remaining visual limitations

- Spelling heuristics are not phoneme recognition or forced alignment. Irregular English words, abbreviations, punctuation and non-English text may be mistimed; unsupported sounds use OPEN. Audio intensity and silence gating help but do not supply linguistic accuracy.
- Lip/eyebrow/cheek/shoulder regions are estimates from the existing face and eye regions. They are not dense landmarks or segmentation. Oblique faces, occluding hair/beards, glasses and already-open mouths can still show artifacts.
- The mouth interior and teeth are procedural, not the person's reconstructed anatomy. Lip textures remain sampled from the immutable original photograph.
- Head motion is a restrained 2D local deformation, not 3D rotation; it cannot reveal unseen face geometry. Shoulder motion uses a soft approximate region and may include adjacent clothing/background.
- Secondary motion is deliberately small. The output is still a procedural animated portrait, not photorealistic generated video. Physical speaker audibility and human perception of realism are not established by automated assertions.

## Optional neural-mode research

Researched after the lightweight system's main checks passed; no model was installed or benchmarked. Optional neural mode remains deferred, and no nonfunctional settings switch was added.

- [LivePortrait's official configuration](https://github.com/KlingAIResearch/LivePortrait/blob/main/src/config/inference_config.py) exposes `flag_force_cpu`. Its [official usage documentation](https://github.com/KlingAIResearch/LivePortrait/blob/main/readme.md) uses a driving video or motion template, and its documented speed evaluation targets NVIDIA GPU. CPU compatibility alone does not establish interactive i5 performance or supply text/audio alignment.
- [SadTalker's official inference code](https://github.com/OpenTalker/SadTalker/blob/main/inference.py) has a CPU option and accepts driven audio. This makes it a potential offline experiment; no acceptable latency on this i5 was verified here.

Decision: retain the working lightweight CPU renderer. Any future optional neural integration needs a separate measured CPU benchmark and isolated dependencies before exposing it as a usable mode. No assertion is made that either model is too slow without that measurement.
