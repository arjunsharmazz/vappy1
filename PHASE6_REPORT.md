# Phase 6: local voice conversation and selected upstream animation components

The existing upload, face detection, Lightweight renderer and Windows speech pipeline are retained. Phase 6 adds explicit microphone recording, local transcription, local streamed replies, short-term memory, sentence-sized speech playback, cancellation and timing diagnostics. The supplied workspace had neural backend files but no registered neural routes or frontend selector; these are now connected as explicit experimental previews.

## Run on this Windows machine

Dependencies and the small conversation models are installed. From two PowerShell terminals:

```powershell
Set-Location 'D:\new project start\backend'
& '.\.venv\Scripts\python.exe' -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location 'D:\new project start\frontend'
npm.cmd run dev
```

Open http://127.0.0.1:5173. If the servers are already running, use the existing page; stop an old server with Ctrl+C before starting another on the same port. The language-model runtime starts automatically on **127.0.0.1:8091**, only when requested, and unloads after five idle minutes. No separate LLM command is necessary.

Upload a portrait. In **VOICE CONVERSATION**, tap **TALK**, permit microphone access, speak, then tap **FINISH RECORDING**. Recording automatically stops at 30 seconds. **STOP CONVERSATION** discards an active recording or stops inference/playback and clears queued speech. **SEND** runs typed text through the LLM. The older **MAKE YOUR AVATAR SPEAK** box still speaks text verbatim. **CLEAR CONVERSATION** clears that browser session's memory. The transcript remains compact and the portrait remains the main visual.

Microphone device names become available after permission. Automatic language detection is the default; English and Hindi/Hinglish hints are available. Existing idle motion continues during listening and thinking. Reduced-motion and Pause idle preferences remain respected.

## Actual engines and models

| Component | Actual implementation | Parameters / precision | Local model bytes |
| --- | --- | --- | --- |
| STT | faster-whisper 1.2.1 / CTranslate2, CPU, four threads | Whisper Tiny multilingual, 39M parameters; INT8 inference on the downloaded converted model | 78,203,619 total model/config/tokenizer/vocabulary bytes |
| LLM | llama.cpp `b11146`, CPU, four threads, 4,096-token context, one slot | Official Qwen3-0.6B GGUF, Q8_0 | 639,446,688 |
| TTS | Existing pyttsx3 SAPI5; existing Windows System.Speech fallback | Installed Windows voices | No new voice model downloaded |
| Neural previews | Existing isolated PyTorch 2.6.0+cpu runtime; selected official LivePortrait modules | Existing four FP32 checkpoint files | 519,927,141; already present before this work |

The llama.cpp Windows CPU runtime download is 18,560,055 bytes. There is no CUDA installation. No SadTalker or MuseTalk checkpoints were downloaded. Source repositories were cloned at the revisions recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Sources: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [converted multilingual Tiny model](https://huggingface.co/Systran/faster-whisper-tiny), [official Qwen GGUF](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF), [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server).

## Installation and provider configuration

Downloads are an explicit setup step. The application never downloads missing models during inference. The setup script prints model size and estimated memory before downloading, caps file sizes and pins the tested runtime. It does not install a large model automatically.

```powershell
Set-Location 'D:\new project start'
& '.\backend\.venv\Scripts\python.exe' -m pip install -r .\backend\requirements-conversation.txt
& '.\backend\.venv\Scripts\python.exe' .\backend\scripts\setup_conversation.py --component all
npm.cmd ci --prefix frontend
```

`SpeechRecognitionEngine` and `LanguageModelEngine` are replaceable provider contracts. Managers own one provider/model instance. To use an already downloaded compatible model, set these before starting the backend:

```powershell
$env:LIVING_STT_MODEL = 'D:\path\to\local-faster-whisper-model'
$env:LIVING_LLM_MODEL = 'D:\path\to\local-model.gguf'
$env:LIVING_LLM_EXECUTABLE = 'D:\path\to\llama-server.exe'
$env:LIVING_AVATAR_NAME = 'Living Avatar'
$env:LIVING_SPEAKING_STYLE = 'friendly, natural and concise'
```

The runtime's HTTP interface is bound to loopback and the provider disables environment HTTP proxies. Its compatible chat endpoint is **local llama.cpp**, not a cloud API. Model paths are developer configuration; browser requests cannot supply model paths or inference URLs. Changing models requires checking that the selected model's chat template and memory requirements fit the machine. The neural worker remains separate from FastAPI's environment.

## Data flow and lifecycle

1. `useMicrophone` requests permission only on TALK, records with MediaRecorder and releases all tracks on finish, cancel, failure or component disposal.
2. `POST /avatar/{avatar_id}/listen` accepts at most 8 MB. PyAV decodes and resamples to bounded 16 kHz mono PCM. Temporary input files are deleted on success and failure. Silence and malformed audio are rejected.
3. Whisper uses `task='transcribe'`, never `translate`, and local files only. Auto language or explicit English/Hindi is passed through.
4. `POST /avatar/{avatar_id}/conversation` streams NDJSON events: status, token, sentence chunk, done or error. The LLM has a bounded response and a 180-second request deadline.
5. The browser displays partial text and queues natural sentence/word-boundary chunks through the existing `/speak` endpoint and `useAvatarSpeech`. Only one utterance plays at a time. Audio amplitude, existing visemes and the existing portrait renderer animate the answer.
6. A generation ID plus AbortController prevents late STT/LLM/TTS replies from restarting playback after Stop. Backend cancellation invalidates pending memory commits. An already running native STT/TTS operation may finish its bounded computation; its result is discarded after Stop. No full-duplex or always-listening mode is implemented.
7. In-memory history retains up to four complete turns with character/context limits, scoped by avatar and random browser-session UUID. Sessions expire after one idle hour and the session count is bounded. Nothing is stored in a conversation database.

Timing diagnostics contain recording duration, actual STT duration, LLM first-token and total generation time, per-chunk TTS request duration, time to first audible playback and total turn duration. They contain metadata, not a saved microphone recording. The benchmark scripts persist only their explicit synthetic test inputs/results.

## Upstream integration

- **SadTalker:** its blink closure profile is adapted to the existing 180 ms browser blink and existing 3–7 second random scheduling.
- **MuseTalk:** its cached lower-face mask and soft blending approach is adapted to the app's existing face regions. This needs no new face parser or model. Exterior pixels stay unchanged; the lower-face mask is used for neural speech frames.
- **LivePortrait:** selected appearance, motion, warping, decoding and camera modules are copied into `backend/app/vendor/liveportrait` and loaded with the existing verified local weights. The app exposes Fast/Balanced/Quality and explicit one-second expression previews. Preview failures leave the original Lightweight renderer working.

These are selected components, not three full neural applications merged together. On this CPU, neural frames are too slow for live speech. Conversation therefore always uses Lightweight animation while neural previews are optional and pre-rendered. The full SadTalker audio-to-motion model and MuseTalk diffusion lip-sync model are not installed or claimed as running.

Complete source/commit/license mapping is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). License copies are retained in the backend vendor directory and frontend distribution.

## Measurements and tests

Actual numeric results are recorded in [conversation_benchmark.json](conversation_benchmark.json) and [neural_integration_benchmark.json](neural_integration_benchmark.json). STT cold and warm runs are distinguished. Browser `time_until_avatar_speaks_seconds` starts at Send/recording completion; `total_including_recording_seconds` includes capture time. TTS chunk time includes the local HTTP request overhead. Backend resource samples include the backend's process tree, not Chrome; CPU percentages in individual request metadata can exceed 100% because multiple cores are active. System-wide CPU figures also include unrelated processes.

Reproducible commands, from the project root, with both servers running for browser/API checks:

```powershell
Push-Location backend
& '.\.venv\Scripts\python.exe' -m unittest discover -s tests -v
Pop-Location
npm.cmd run build --prefix frontend
node frontend/tests/phase2.cjs
node frontend/tests/phase3.cjs
node frontend/tests/phase4.cjs
node frontend/tests/mouth.cjs
& '.\backend\.venv\Scripts\python.exe' backend/scripts/benchmark_conversation.py
node frontend/tests/phase6.cjs
& '.\.tools\neural-venv\Scripts\python.exe' backend/scripts/benchmark_integrated_neural.py
& '.\backend\.venv\Scripts\python.exe' backend/scripts/check_neural_api.py
```

Run inference benchmarks and speech tests sequentially. The browser suite uses local Chrome and the development Playwright installation already under `.tools/node_modules`; the Phase 6 test uses a WAV-backed virtual microphone. The benchmark script generates that WAV through the actual Windows TTS first. A real person's microphone, room acoustics and physical speaker output are not certified by those automated tests.

## Known limitations

- Whisper Tiny is chosen for size and CPU cost. It can misrecognize names (the test fixture's “Arjun” was transcribed as “Arjan”) and mixed-language speech. Hindi/Hinglish audio accuracy has not been validated against representative human recordings. No automatic translation is requested.
- Qwen3 0.6B is a small model. Replies can be simplistic, repeat a question or confuse pronouns even when the correct name remains in context. It is not a substitute for a larger, more capable model. The provider is replaceable without rebuilding the UI.
- This machine exposes only Microsoft Hazel, David and Zira English SAPI voices. Natural Hindi speech output needs a suitable separately installed local voice; the existing TTS engine has not been replaced. Hindi text remains visible if TTS fails.
- The existing viseme timing is heuristic, mainly English spelling based. Neither the neural preview nor the procedural mouth reconstruction establishes phoneme-accurate Hindi lip sync.
- Neural animation is pre-rendered and may have crop/identity artifacts, particularly for oblique or occluded faces. The original image is preserved. Live conversation deliberately uses the measured faster Lightweight renderer.
- Microphone permission needs a secure context such as localhost. Browser/device availability errors allow retry or text input. Stop aborts playback immediately, but native recognition or a synthesis already underway may finish before its resource lock is released.
- Existing generated speech WAVs follow the previous avatar audio retention behavior. **Microphone recordings are temporary and deleted.** Clear removes conversational memory, not previously generated TTS files.

## Files created or modified

Created: `backend/requirements-conversation.txt`; `backend/app/services/conversation_routes.py`; the `speech_recognition/` and `local_ai/` packages; `neural_avatar/blending.py`; selected `backend/app/vendor/` modules and license files; setup/benchmark/API-check scripts under `backend/scripts/`; `backend/tests/test_conversation.py`; `frontend/src/hooks/useMicrophone.js`, `useConversation.js`; `frontend/src/components/ConversationPanel.jsx`, `NeuralControls.jsx`; `frontend/src/animation/blinkProfile.js`; `frontend/src/phase6.css`; `frontend/tests/phase6.cjs`; distributed license files; this report, both benchmark JSON files and the third-party notice.

Modified: `backend/app/main.py`; neural `base_engine.py`, `model_loader.py`, `preprocessor.py`, `worker.py`, `engine_manager.py`, `routes.py`; `frontend/src/main.jsx`, `hooks/useAvatarSpeech.js`, `animation/PortraitEngine.js`; the old phase-label assertion in `frontend/tests/phase2.cjs`; `.gitignore`; README's Phase 6 pointer. Model files and full source checkouts remain local ignored assets.

No cloud inference, paid API, voice cloning, camera capture, face recognition, internet search inside the app, long-term database, wake word, home automation or deployment features were added.
