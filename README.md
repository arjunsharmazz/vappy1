# AI Living Frame - Phase 6: Local Voice Conversation

## Facial expressions (prepared neural face, atlas v4)

Prepared poses now include a full smile with cheek lift, laugh poses (played as softening "ha-ha" bursts), eyebrow raise and frown, plus vertical gaze for the upcoming camera tracking. Controls: **Smile**, **Laugh**, **Blink**, **Eyebrows**, **Look Left/Right**. Eyebrows also lift slightly during speech, and an idle face occasionally shows a soft smile. An existing portrait upgrades automatically on first open: earlier poses are reused and only the new ones are rendered (a few minutes on CPU). Reloading the page or opening a second tab during preparation now joins the running job instead of showing "Neural engine is busy".

## Camera eye tracking and ready-made replies

**Eye tracking:** the backend reads the webcam (`[vision]` in `config/settings.toml`), finds the nearest face with OpenCV YuNet (`.tools/models/yunet/face_detection_yunet_2023mar.onnx`, Haar fallback) and streams only the face position to the browser (`GET /vision/stream`). The avatar's eyes follow the person with smooth pursuit, quick saccades, small fixation movements and occasional glances away; with nobody in front they wander calmly. The camera runs only while a portrait page is open and tracking is on, stops about 10 seconds after, and frames are never saved. No camera means no tracking and no error. Test the camera alone from `backend/`: `.venv\Scripts\python.exe -m app.vision.check`. If the eyes move the wrong way, set `mirror = false`.

**Ready-made replies:** `config/replies.json` holds common phrases in English, Hinglish and Hindi (greetings, how are you, name, time, date, thanks, bye, joke, food, tired, sad and more). A match answers instantly, without the LLM; English input gets English replies, Hindi/Hinglish input gets Roman-script Hinglish replies. Edit the file while the app runs. Anything else goes to the local LLM.

## Full-screen frame and natural Hindi voice

The page is now just the portrait, full screen. A small rail at the top right holds the **☰ menu** and three status lights (🎙 listening, 👁 person in front, 🔊 speaking; a red dot on ☰ means something needs attention). The menu slides in from the right with photo upload, expressions, voice conversation, typed speech and animation settings; Esc or a click outside closes it. Hands-free conversation and the camera keep running while it is closed. The developer mouth-debug overlay appears only with `?debug=1`.

Speech uses **Piper** (offline neural TTS, works on Windows and Raspberry Pi) with the Indian Hindi voice `hi_IN-priyamvada-medium` (female) or `hi_IN-pratham-medium` (male), set in `[tts]` of `config/settings.toml`; Windows SAPI is the fallback. Install with `pip install -r backend/requirements-conversation.txt` and put the voice `.onnx` + `.onnx.json` files in `.tools/models/piper/`. The Hindi voice pronounces Devanagari naturally but reads Roman Hinglish with an English accent, so Hindi/Hinglish replies (ready-made, commands, greetings, fillers and the LLM) are written in Devanagari; English questions still get English answers. `[persona] gender` switches Hindi verb forms (करती हूँ / करता हूँ). Identical sentences are cached, so repeated replies play instantly.

## Start-up and the ready-made catalogue

When the face is ready, the avatar starts the conversation by itself (`start_on_load`): it turns on hands-free listening and asks for the person's name (`ask_name_on_start`), saving whatever name is said next. Desktop browsers only allow sound after a tap, so a "Tap to start" prompt appears on the frame; a kiosk browser with autoplay allowed (Raspberry Pi) starts without it. `config/replies.json` now holds 105 question types with 1,036 English/Hinglish/Hindi phrasings (about the avatar, likes, stories, riddles, feelings and care, daily routine, festivals and general knowledge).

## Hands-free conversation and smart commands

Press **🎙 HANDS-FREE** in Voice Conversation (or set `hands_free = true` in `[conversation]`). The browser listens continuously, detects when you start and stop speaking (adaptive energy detector in an AudioWorklet, no extra model), sends the utterance to local Whisper, and the avatar answers with the existing voice and lip-sync, then listens again. The microphone is ignored while the avatar thinks or speaks, so it does not answer itself. `allow_interrupt = true` lets a clearly louder voice stop the avatar (use headphones or an echo-cancelling speaker). With the camera on, someone walking up is greeted automatically and asked their name if it is not known yet.

Commands handled in code before ready-made replies and the LLM (`backend/app/brain/skills.py`):
- **Name:** "my name is Arjun", "mera naam Arjun hai", "मेरा नाम अर्जुन है"; ask "what's my name?" / "mera naam kya hai?".
- **Remember:** "remember that I like tea", "yaad rakhna ki kal doctor ke paas jana hai"; "what do you remember?" / "tumhe kya yaad hai?"; "forget everything" / "sab bhool jao". Stored in `avatar_data/<id>/memory.json`; also given to the LLM.
- **News:** "today's news", "aaj ki khabar sunao", "समाचार". Uses the RSS feed in `[news]` when online; offline it reads the last saved headlines or says there is no internet.
- **Maths:** "what is 12 times 4", "5 plus 3 kitna hota hai", "१० भाग ४".

## Configuration (new): one file for all settings

All settings live in **[config/settings.toml](config/settings.toml)**: device profile (`auto` / `pc` / `pi4`), log level, persona, speech recognition, local LLM, TTS speed, camera (for the upcoming eye tracking) and conversation mode. Edit the file and restart the backend. Relative paths resolve from the project root. Invalid values are logged and replaced by safe defaults, so the app still starts. Secrets (none needed now, everything is offline) go in `config/.env`; copy `config/.env.example`. The older `LIVING_*` environment variables still work and override the file. `LIVING_CONFIG` can point to another settings file. `GET /config` returns only non-secret settings for the frontend. On a Raspberry Pi, `profile = "auto"` selects the lighter `pi4` profile (fewer threads, smaller LLM context). Roadmap and status: [PROJECT_ANALYSIS.md](PROJECT_ANALYSIS.md).

**Avatar update:** `Prepared neural face` is now the default animation mode. On the first upload it prepares 21 local LivePortrait poses (several minutes on CPU); matching images reuse the cache. Version 2 includes rounded/wide mouth shapes and four eyelid closure stages. Existing version 1 poses are reused during upgrade. After preparation, speech and blinking use the cached neural images. The original photo stays visible during preparation or failure. Lightweight animation and neural video previews remain available in the Animation selector. This is approximate pose playback, not full audio-conditioned neural video. See [the actual-portrait review](AVATAR_INTEGRATION_REVIEW.md) for captures, measurements and limitations.

Phase 6 adds microphone recording, local Whisper transcription, a small local llama.cpp language model, session memory and streamed replies through the existing TTS/animation. See **[PHASE6_REPORT.md](PHASE6_REPORT.md)** for current setup, exact Windows commands, measurements, tests and limitations. Selected components from SadTalker, MuseTalk and LivePortrait are documented in **[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)**. The earlier phase documentation below remains useful for the original portrait and speech controls.

A local animated portrait prototype for Windows 10, Intel Core i5 and 16 GB RAM. Phase 3 extends the existing React/Vite/Tailwind and FastAPI/OpenCV app with offline Windows speech and an audio-reactive mouth. No cloud API, GPU, CUDA, Docker, database, authentication, microphone, LLM or generative video is used.

Internet is needed for initial dependency installation only. All image processing, models, fonts, icons and animation run locally after setup.

## Run on this machine

The virtual environment, pyttsx3 and frontend dependencies are already installed in this workspace. Open **two terminals**. Stop an old backend with Ctrl+C before starting the updated one. Reload the browser after restarting.

**PowerShell — backend:**

```powershell
Set-Location 'D:\new project start\backend'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**PowerShell — frontend:**

```powershell
Set-Location 'D:\new project start\frontend'
npm.cmd run dev
```

Open **http://127.0.0.1:5173**. Leave both terminals open. Ctrl+C stops a server. Health: http://127.0.0.1:8000/health. API docs: http://127.0.0.1:8000/docs.

If you use normal **CMD** and are already at `D:\new project start>`:

Backend:
```cmd
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend, in another CMD at the project root:
```cmd
cd frontend
npm run dev
```

Vite proxies `/avatar`, `/uploads` and `/health` to port 8000. Both servers bind to loopback. No environment variables are required. Use the development server for this prototype; `vite preview` does not provide the configured API proxy.

## First-time setup / another Windows machine

Use Windows 10 64-bit, Python 3.11 64-bit and Node.js 22 or 24 with npm.

**1. Create the Python environment:**

```powershell
Set-Location 'D:\new project start'
py -3.11 -m venv .\backend\.venv
```

This workspace uses a portable Python 3.11 runtime because the system Python launcher was unusable. If recreating the environment here, use:

```powershell
Set-Location 'D:\new project start'
& '.\.tools\python\tools\python.exe' -m venv .\backend\.venv
```

Do not delete `.tools/python` while using this virtual environment. That directory is ignored by Git; on another computer install Python 3.11 and use `py -3.11`.

**2. Install backend dependencies:**

```powershell
Set-Location 'D:\new project start'
& '.\backend\.venv\Scripts\python.exe' -m pip install -r .\backend\requirements.txt
```

**3. Start FastAPI** using the backend command above.

**4. Install frontend dependencies:**

```powershell
Set-Location 'D:\new project start\frontend'
npm.cmd ci
```

**5. Start React** using `npm.cmd run dev`.

Phase 3 adds pyttsx3 2.99 on Windows (which installs comtypes, pypiwin32 and pywin32). OpenCV already bundles the face and eye Haar cascades. Calling the virtual environment's Python directly avoids activation and execution-policy changes.

## Use

1. Upload or drop a clear, front-facing JPG/JPEG/PNG, up to 10 MB and 20 megapixels.
2. A valid portrait displays **Avatar Ready**, its avatar ID and a **LIVE** indicator. Subtle facial breathing and automatic blinking start once the image loads. Each blink lasts about 180 ms; the next delay is freshly randomized between 3 and 7 seconds.
3. Click **Smile**, **Laugh**, **Blink**, **Look Left** or **Look Right**. Each action returns to **IDLE** automatically; a new click replaces the current action.
4. **Pause idle** stops automatic breathing/blinking. Manual actions still work. **Resume idle** restores automatic motion.
5. In **MAKE YOUR AVATAR SPEAK**, type up to 500 characters and press **SPEAK**. The small Speak control beside Smile/Laugh focuses this text panel.
6. The status moves through **GENERATING VOICE** to **SPEAKING**. The browser plays the generated WAV through your default speakers and the mouth reacts to its amplitude. The frame scrolls into view when playback starts.
7. Press **STOP** in the speech panel or beside the frame status to stop playback. When playback finishes or stops, the mouth closes and the avatar returns to Idle/Live. Speak can be used again immediately.
8. Open **Speech diagnostics** to see the avatar ID, TTS/audio state, animation state and measured audio amplitude.

No-face photos retain the exact message: “No face detected. Please upload a clear front-facing photo.”

If a face is valid but two usable eye regions cannot be found, the photo is saved and shown statically with: “Avatar created, but advanced facial animation is unavailable for this photo.”

Image-loading failures and animation errors show feedback. Renderer failure falls back to the original portrait. Hidden tabs suspend animation, and the system's reduced-motion preference disables automatic animation by default. Manual controls remain available.

## Processing and performance

The backend validates and normalizes each image, chooses the largest detected face, detects eye regions with OpenCV's bundled eye cascade, and estimates the mouth near its expected anatomical position using a local intensity search. These are **approximate facial regions**, not a dense landmark model. Coordinates use saved-image pixels; left/right names refer to the viewer's sides.

The saved image has a longest edge of at most 1600 pixels. Face/eye analysis uses a longest edge of at most 800 pixels and two OpenCV CPU threads. Work is dispatched off FastAPI's async event loop. No backend calls are made for expressions or idle animation. Speech uses one local POST to generate a WAV and one local GET to fetch it; mouth animation runs entirely in the browser.

The browser caches source pixels once, precomputes displacement weights, and applies bilinear pixel warping to a face patch capped at 280 pixels per side. Rendering targets 60 fps and backs off to 30 when the moving average render cost exceeds 12 ms (returns to 60 below 9 ms), on a canvas with a longest edge of at most 900 pixels. The eye warp narrows only the eye regions; smile warping lifts/widens the mouth corners with cheeks, eye narrowing and subtle brows; laugh adds coordinated jaw, mouth, cheek and local head motion; look shifts the eye regions. Phase 3.5 separates the original upper/lower lip pixels using a feathered inverse warp and composites a shaded maroon cavity, muted tongue and individually curved warm teeth behind their mask. A local chin displacement follows opening. REST and M/B/P fully close; A, E, I, O, U, F/V, TH, L, S/Z and OPEN blend with audio-controlled strength. Phase 4 replaces the pseudo-viseme sequence with English spelling heuristics, weighted word/letter timings, punctuation pauses and a timeline fitted to the decoded WAV duration. Leading/trailing silence and nearby word-boundary minima are estimated once from the PCM. Playback follows AudioContext time, while the existing smoothed amplitude controls intensity; this is approximate alignment, not phoneme recognition. The original source is immutable. A one-time local seam refinement uses the saved mouth region, without repeating face detection. The image frame and exterior background stay fixed; the approximate shoulder mask can include adjacent background pixels. This is a replaceable CPU canvas engine, with no WebGL or neural inference.

Actual speed depends on the CPU and browser. These bounds are performance controls, not a guaranteed frame rate or a Raspberry Pi benchmark.

## Local files and architecture

```text
frontend/
  src/main.jsx                       Existing upload/page UI
  src/components/
    DigitalFrame.jsx                 Frame shell and drag/drop
    AvatarViewer.jsx                 Image loading and engine lifecycle
    AvatarControls.jsx               Expressions and idle pause
    AvatarStatus.jsx                 Ready/live/status/ID display
  src/animation/PortraitEngine.js     Animation states and local pixel warps
  src/styles.css                     Existing premium theme
  src/phase2.css                     Phase 2 additions
  src/phase3.css                     Speech panel and playback styling
  src/hooks/useAvatarSpeech.js       WAV playback, analyser and cleanup
  src/components/SpeechPanel.jsx     Text input, Speak/Stop and diagnostics
  tests/phase2.cjs                    Expression regression browser checks
  tests/phase3.cjs                    Real Windows TTS and browser checks
backend/
  app/config.py                      Existing paths/limits
  app/imaging.py                     Validation, face detection, coordinates
  app/services/face_landmarks.py      Eye detection and mouth estimate
  app/services/avatar_store.py        Persistence and legacy compatibility
  app/services/tts_service.py         Serialized synthesis and WAV validation
  app/services/tts_worker.py          Isolated pyttsx3/SAPI process
  app/services/tts_fallback.ps1       Offline System.Speech fallback
  app/main.py                        FastAPI routes
  tests/test_upload.py                Phase 1 regression checks
  tests/test_phase2.py                Retrieval and fallback checks
  tests/test_speech.py                Speech validation/API/error checks
uploads/
  <avatar_id>.jpg                     Phase 1 URL compatibility copy
avatar_data/
  <avatar_id>/
    original.jpg                     Normalized source portrait
    avatar.json                      Regions, status, timestamps, dimensions
    audio/<speech_id>.wav            Generated local speech files
```

`original.jpg` is the normalized JPEG used by the renderer, not a byte-for-byte original upload. Original EXIF metadata and transparency are not retained. Valid no-face images are also saved.

Existing Phase 1 flat `avatar_data/<id>.json` records and `uploads/<id>.jpg` images remain readable. They display statically because they have no landmarks. Re-upload an old portrait to obtain Phase 2 animation; old files are not migrated or deleted.

There is no gallery or session restore. Photos persist locally until manually removed. For a new avatar, remove its UUID directory and matching `uploads/<id>.jpg` to delete it.

## API

- `GET /health` — unchanged: `{"status":"ok","device":"cpu"}`.
- `POST /avatar/upload` — unchanged multipart field `file`; original response fields are preserved and Phase 2 metadata is added.
- `GET /avatar/{avatar_id}` — metadata, dimensions, face box, landmarks and animation availability.
- `GET /avatar/{avatar_id}/image` — locally stored JPEG.
- `GET /uploads/{avatar_id}.jpg` — preserved Phase 1 image route.

There is no expression-action endpoint because all animation state is browser-local. The speech routes below generate and serve audio only.

Example upload/metadata result:

```json
{
  "success": true,
  "avatar_id": "generated-uuid",
  "face_detected": true,
  "status": "ready",
  "message": "Avatar Ready",
  "image_url": "/avatar/generated-uuid/image",
  "image_width": 512,
  "image_height": 512,
  "face_box": {"x": 150, "y": 100, "width": 200, "height": 200},
  "landmarks": {
    "left_eye": {"x": 205, "y": 170, "width": 35, "height": 15, "source": "haar"},
    "right_eye": {"x": 285, "y": 170, "width": 35, "height": 15, "source": "haar"},
    "mouth": {"x": 245, "y": 250, "width": 72, "height": 24, "source": "estimated"},
    "face_center": {"x": 250, "y": 200}
  },
  "animation_available": true,
  "warning": null
}
```

Records also include `created_at`, `schema_version` and `landmark_method`. `success` means processing/storage succeeded, even when `face_detected` is false. Invalid requests return 400/413/415/422 with `detail`; missing avatar files return 404; unreadable/corrupt records or images return 422; unexpected upload/storage failures return 500.

## Tests and builds

```powershell
Set-Location 'D:\new project start\backend'
& '.\.venv\Scripts\python.exe' -m pip install -r .\requirements-dev.txt
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
& '.\.venv\Scripts\python.exe' -m compileall -q app
Set-Location '..\frontend'
npm.cmd run build
```

With both servers running:

```powershell
Invoke-RestMethod 'http://127.0.0.1:5173/health'
curl.exe -F 'file=@C:\path\to\portrait.jpg' http://127.0.0.1:5173/avatar/upload
Invoke-RestMethod 'http://127.0.0.1:8000/avatar/REPLACE-WITH-RETURNED-UUID'
```

Optional browser suite requires installed Google Chrome and development-only Playwright under ignored `.tools` (already available here):

```powershell
Set-Location 'D:\new project start'
npm.cmd install --prefix .tools --no-save playwright
node .\frontend\tests\phase2.cjs 'C:\path\to\clear-portrait.jpg'
```

Use a test portrait with both eyes detectable. The suite creates its own avatars and removes only those generated records. It writes screenshots under `.tools`. In this workspace, omitting the portrait argument uses the OpenCV sample already downloaded for Phase 1 checks. No fixture is fetched by the application or the test script.

## Known limitations

- Approximate 2D warps are subtle and not photorealistic animation. Smiles do not synthesize teeth; laughs have a procedural mouth interior and teeth but no audio; looking shifts eye regions rather than producing a 3D head turn.
- Mouth location is estimated. Facial hair, glasses, profiles, closed eyes, occlusion, lighting and tilted faces can reduce accuracy or cause artifacts. One well-lit, front-facing portrait works best.
- Only the largest detected face is animated. Haar detection can miss faces or yield false positives.
- Unreliable eye detection intentionally leaves the portrait static with the requested warning.
- Raspberry Pi deployment and performance validation have not been done. Speech synthesis currently requires Windows SAPI. No microphone, recognition, chatbot, voice cloning or neural lip-sync is implemented.

References: [OpenCV face/eye cascades](https://docs.opencv.org/4.13.0/db/d28/tutorial_cascade_classifier.html), [Canvas pixel rendering](https://developer.mozilla.org/en-US/docs/Web/API/CanvasRenderingContext2D/putImageData), [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/).

## Previous Phase 2 verification

- 18 backend tests passed, including Phase 1 regression cases, UUID validation, new storage/retrieval, missing/corrupt images and metadata, legacy records, landmark-failure fallback, coordinate scaling and CORS.
- Python imports/compilation passed. `pip check` reported no broken requirements.
- Vite production build passed (34 modules).
- Real Chrome browser upload through Vite to FastAPI passed with a sample portrait and actual OpenCV face/eye extraction; metadata and image retrieval passed.
- Smile, Blink, Laugh, Look Left and Look Right each changed portrait pixels, preserved the tested background region and returned to Idle. Automatic blink also returned to Idle.
- Hidden-page pause/resume, reduced-motion default, mobile layout without horizontal overflow, and absence of uncaught page errors passed.
- A real blank PNG drag/drop returned the exact no-face message. A corrupt image returned validation feedback.
- Injected renderer failure fell back to the original image. Simulated missing landmarks, missing image responses and backend unavailability produced the expected feedback.
- Screenshots were visually reviewed on desktop and mobile. Tests verified bounded rendering behavior, but no full CPU-utilization benchmark or Raspberry Pi test was performed.


## Phase 3 offline speech setup

If updating a copy that does not have the new dependency yet:

```powershell
Set-Location 'D:\new project start'
& '.\backend\.venv\Scripts\python.exe' -m pip install -r .\backend\requirements.txt
```

Restart the backend using the command at the top of this README, then refresh the browser with Ctrl+Shift+R. No new frontend dependency is needed. Re-upload the portrait to use the improved mouth-position estimate; old metadata is preserved.

Windows must have an installed desktop SAPI voice. This prototype uses the default installed voice at 175 words/minute. English was tested; language/pronunciation depends on the voices installed on your PC. This is synthetic Windows speech, not a clone of the photographed person's voice.

pyttsx3 initializes inside a short-lived worker process so COM/SAPI state cannot leak between FastAPI request threads. Only one generation runs at a time; simultaneous requests return 429. The primary worker has a 45-second timeout. If it fails or produces an invalid file, an installed Windows System.Speech fallback gets its own 45-second timeout. The fallback runs a fixed local PowerShell script with a process-only execution-policy override; user text is passed as JSON data, never as code.

Each result is checked for PCM WAV format, complete frames, duration, sample rate and non-silent samples before it is published. Zero-byte, truncated and silent files never return success. Invalid pending files are removed.

During development, the restricted tool sandbox denied Windows SAPI voice access. Generation and the running backend were tested outside that sandbox. The normal PowerShell/CMD launch command on this machine works without an administrator terminal.

The browser creates/resumes AudioContext during the button click, fetches and decodes the local WAV, then connects BufferSource -> AnalyserNode -> speakers. Time-domain RMS drives a smoothed mouth opening from 0 to 0.75. Silence closes the mouth. Its analyser animation frame, source, nodes and AudioContext are cleaned up after end, Stop, error, photo replacement or unmount. The separate idle renderer resumes as appropriate. Natural blinks can overlap speech without interrupting it.

Stop during generation aborts the browser request and prevents a late response from playing. A synthesis already running on the backend may finish and save its WAV; it remains local. Saved speech files are retained until their avatar's audio directory is manually removed.

### Speech API

`POST /avatar/{avatar_id}/speak`

```json
{"text":"Hello! I am your AI Living Frame. Now I can talk."}
```

```json
{
  "success": true,
  "speech_id": "generated-uuid",
  "audio_url": "/avatar/avatar-uuid/audio/speech-uuid",
  "message": "Speech generated",
  "tts_engine": "pyttsx3-sapi5",
  "duration_seconds": 5.33
}
```

The response also includes sample rate, channels, WAV byte count, RMS and peak amplitude. `GET /avatar/{avatar_id}/audio/{speech_id}` serves `audio/wav`. Both IDs are validated and filesystem paths are never accepted from the request. Empty/whitespace-only text, over 500 characters, unsupported controls, non-string values and text without words/numbers return 422. A no-face avatar returns 409; a busy engine returns 429; voice failure returns 503; missing/corrupt audio returns 404/422.

### First talking test

1. Upload a clear portrait with visible eyes and mouth.
2. Enter exactly: **Hello! I am your AI Living Frame. Now I can talk.**
3. Press SPEAK, with your Windows output device connected and its volume audible.
4. Confirm speech, a moving mouth, occasional blinks and a return to LIVE after the sentence.
5. Speak again, then try STOP. Audio and mouth movement should stop immediately.

The browser tests verify WAV decoding, active Web Audio playback, nonzero analyser samples, visible mouth-pixel changes, natural blink overlap, end cleanup, repeat playback and Stop. They cannot independently confirm your physical speaker volume, routing or what you personally hear.

If there is no sound, open diagnostics: TTS ERROR indicates generation; Audio ERROR indicates fetching/decoding/playback. If Audio is PLAYING with nonzero amplitude, check browser/site muting and Windows Volume Mixer/default output. If mouth movement is misplaced, use a front-facing photo and upload it again. Mouth placement is still approximate; this procedural compositor is not phoneme-accurate lip sync. In development, SHOW MOUTH DEBUG displays approximate corners, upper/lower lip anchors, center, warp region, current viseme, opening and teeth visibility, plus FPS, smoothed render cost, state, audio amplitude, jaw offset, gaze, blink and head angle. Its shape selector previews each viseme for tuning. It is off by default and absent in production.

### Additional browser check

With both servers running and the development-only Playwright installation under `.tools`:

```powershell
Set-Location 'D:\new project start'
node .\frontend\tests\phase3.cjs
```

The default fixture is the local development portrait under `.tools/face-test.jpg`. To use another clear portrait, append its full path as the first argument. The test plays real generated speech through Chrome's default audio output; no cloud requests are used. It removes only avatars/audio it creates.


### Phase 3.5 renderer checks

With both servers running, run `node frontend/tests/mouth.cjs` for the saved front-facing portrait, or pass another saved avatar directory. The check renders all eight visemes, writes `.tools/viseme-sheet.png`, verifies that the original lip mask opens over an opaque interior, checks closure/teeth hiding, and repeats five cycles to detect source mutation or rest drift. A one-color-level tolerance accounts for browser canvas rasterization differences.

`node frontend/tests/phase3.cjs` exercises actual Windows speech with ?Hello, my name is AI Living Frame. Now I can actually talk to you.? It verifies browser audio, changing mouth shapes, teeth visibility, blink overlap, completion, Stop, repeated speech and error recovery. `node frontend/tests/phase2.cjs` covers the existing expressions and UI. Clear front-facing portraits give the most reliable mouth placement; the source contains approximate regions rather than dense lip contours.


## Phase 4 behavior and validation

`visemeTimeline.js` analyzes text before synthesis and fits the mouth timeline once audio is decoded. `visemeEngine.js` blends the selected shapes with measured audio intensity. `IdleBehaviorController.js` schedules occasional gaze/tilt or speaking brow/nod events, avoids consecutive identical event types, and defers new events during blinks. Cached eyebrow and cheek regions, local feathered head deformation and a separate masked shoulder patch add secondary motion. Shoulder breathing is skipped when the visible area below the face is too small. These regions are approximations derived once from the saved face/eye data, not new detections.

Speaking takes priority over expressions. Clicking Smile/Laugh during speech queues the latest request; it plays after speech ends. Blink can overlap expressions. Smile eases back to neutral before the paused renderer stops. Pause idle/reduced-motion disables spontaneous gaze, brows, tilt/nods and breathing; explicit expressions and speech still animate, and speech retains natural blinks.

Run all checks from the project root:

```powershell
Push-Location backend
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
Pop-Location
npm.cmd run build --prefix frontend
node frontend/tests/mouth.cjs
node frontend/tests/phase2.cjs
node frontend/tests/phase3.cjs
node frontend/tests/phase4.cjs
```

For backend checks, run from `backend` instead if `app` is not on PYTHONPATH: `& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v`. Browser tests require both servers and local Chrome/Playwright. Run speech tests sequentially because the local synthesizer intentionally handles one request at a time. The Phase 4 test watches 20 seconds of real idle frames, exercises coordinated smile/laugh, speaks the requested Phase 4 sentence five times, checks original-pixel restoration with idle paused, and checks queued-smile priority. It saves `.tools/phase4-results.json` and visual snapshots.

Remaining limitations: spelling is not pronunciation, so irregular English words and other languages will be approximate. Mouth/brow/shoulder regions are not semantic segmentation; oblique poses, occlusion and already-open mouths may show artifacts. Teeth/interior are procedural, not reconstructed anatomy. Subtle head movement is a 2D warp and does not reveal new viewpoints. Frame rate and render cost depend on CPU/browser load; CPU utilization was not measured. The optional neural mode was researched but is not installed or exposed without a validated CPU benchmark; see `PHASE4_REPORT.md`.
#   v a p p y 1  
 