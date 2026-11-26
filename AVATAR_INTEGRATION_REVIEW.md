# Avatar integration review — 2026-09-26

## Naturalness pass: vowel shapes and eyelids

Prepared-pose version 2 adds opening levels for rounded and wide lips. Playback now mixes open/rounded/wide neural mouth families using the smoothed speech parameters, rather than representing every vowel with the same opening sequence. Closed M/B/P and silence retain the original closed mouth. This remains driven by estimated spelling/audio timing, not recognized phonemes.

Blink preparation now has four neural closure stages (.25, .5, .75, 1), plus the original open eyes. A brisk close, short closed interval and slower reopening replace the symmetric timing in prepared mode. Each eyelid frame is still a single neural pose, avoiding the doubled iris caused by dissolving open and closed eyes.

On the saved user portrait, 13 poses were reused and 8 new poses were rendered; the upgrade took **225.08 seconds**. Version 2 contains 21 neural poses plus the source tile. A completely new portrait will take longer than the earlier 13-pose preparation; exact time depends on CPU load. Versioned cache keys keep the previous atlas intact.

The browser regression checks distinguish rounded/wide mouths at equal opening, verify no mouth-shape changes outside the lower face, check all four learned eyelid stages, and exercise real speech/Stop and failure fallback. `.tools/naturalness-poses.png` shows the inspected poses; `.tools/actual-avatar-natural.webm` and its PNG/JSON capture the real UI replay. Changes are deliberately local to lips and eyelids; no head/shoulder stretching was reintroduced.

## Actual portrait replay and prepared neural playback

The user's saved portrait `6ae85cc8-ed09-4fdc-9da2-956c6a7c325f` was run through the real browser UI: idle, smile, laugh, blink, gaze and actual Windows TTS playback. Captured frames showed the old renderer flattening eye-area skin and opening a procedural horizontal mouth cavity. Earlier sample-portrait tests did not establish acceptable quality on this photo.

Native-resolution LivePortrait renders on this same portrait produced plausible eyelid and mouth geometry, taking about 21–25 seconds per frame. A new prepared-pose path now renders and caches a bounded set once, then blends neighboring mouth poses in the browser at the audio playback time. Eyelids select a single neural pose rather than cross-fading open eyes over closed lids. Local masks keep eye changes separate from mouth changes. The original portrait is drawn at rest and while preparation is unavailable; this mode never silently falls back to procedural teeth or eyelid squashing.

Preparation took **317.18 seconds** for 13 neural poses on this machine. The local cache is keyed by source image, face regions, model revision and render configuration, reused across matching uploads, and bounded to eight atlases / 512 MiB. `Prepared neural face` is the new default. Lightweight and pre-rendered video previews remain selectable. Saved portraits can be opened with `/?avatar=<id>`.

Actual speech capture measured about **60.8 FPS / 0.57 ms mean draw time** with prepared poses, versus **29.4 FPS / 13.2 ms** in the previous canvas capture. These are local browser observations, not guarantees on other hardware. Inspection artifacts are `.tools/actual-avatar-before.webm`, `.tools/actual-avatar-after.webm` and the corresponding PNG frame sheets / JSON measurements. Visual inspection uses the captured frames; the recordings are retained for playback review.

Validation includes real TTS/Stop, cache reuse, unchanged upper face during mouth motion, unchanged mouth during a simultaneous blink, unchanged background, restoration within Chromium's one-code-value rounding, original-photo fallback on preparation failure, atlas mask/dimension checks and cancellation before publishing. Commands: `node frontend/tests/prepared-avatar.cjs <prepared-avatar-id>`, `node frontend/tests/inspect-avatar.cjs <id> after`, backend unit tests, and `npm.cmd run build --prefix frontend`.

This remains an approximation: a finite pose bank driven by estimated speech timing, not full audio-conditioned video synthesis or phoneme recognition. Neural detail can be softer than the original; teeth are model-generated; blink states are discrete. Round/wide poses are cached but currently playback uses the denser opening sequence to avoid large cross-fades. No perfect realism or identity-preserving dental reconstruction is claimed.

## Follow-up: rubber-like live face distortion

The browser renderer previously warped the center of the head independently of the neck/background, lifted cheeks and brows, and stretched a shoulder patch. These transforms are now removed. Smile and gaze displacement are reduced; inferred mouth opening is reduced from 1.10 to 0.58 times the estimated mouth height, width variation is damped, and inferred jaw motion is reduced. A per-pixel motion mask restricts the low-resolution overlay to moving regions so untouched face detail remains the original photograph.

The browser mouth regression test now asserts that synthetic head/nod/breath signals cannot alter the resting photo. It also checks all visemes, restoration and overlapping blinks. This test and the frontend build passed. Before/after sheets are saved at `.tools/viseme-before-natural.png` and `.tools/viseme-sheet.png` and were visually inspected. This is a conservative correction to Lightweight animation; it does not change the separate neural preview or establish photorealistic speech.

The local checkouts were compared with the running application. LivePortrait's appearance extractor, motion extractor, warping network and decoder were already vendored and loaded with real local weights. SadTalker contributes a blink profile and MuseTalk contributes an adapted feathered face compositor. Their complete audio-driven models are not installed.

This change extracts LivePortrait's eye-direction, smile and three lip-expression functions from the pinned Gradio pipeline into a dependency-free numerical module. Look previews now move the eyes along with the head. The speech control mapping uses upstream lip-depth and vertical controls instead of displacing a lip point sideways for round vowels. Slider-to-audio mapping is still heuristic. Previously generated clips are invalidated through a cache version change.

The preview UI previously cancelled every render after two minutes, including renders still producing frames. It now measures time without progress and allows three minutes per stalled stage. Cancellation remains available.

Validation: 42 backend tests passed, including numerical comparisons with the actual upstream functions, image-cache checks and unchanged-background checks. The production frontend build passed. Real CPU inference produced neutral, smile and speech frames; the speech frame was visually inspected. Timings and the local preview API check are recorded in `neural_integration_benchmark.json`.

Limits: the current face/eye regions are approximate; learned landmark, stitching and eye/lip retargeting models are not part of this integration. Live conversation still uses the browser renderer; neural expressions are pre-rendered previews. The measured CPU frame times cannot support real-time neural video. These changes do not establish perfect lip synchronization or equal quality across portraits, and do not constitute full SadTalker/MuseTalk integration.
