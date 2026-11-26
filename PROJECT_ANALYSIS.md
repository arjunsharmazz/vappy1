# PROJECT ANALYSIS — AI Avatar Frame ("AI Living Frame")

> Date: 2026-11-09 · Phase 1 (sirf analysis, koi code change nahi)
> Scope: poora repo, **`third_party/` folder skip kiya gaya** (user ki request par).
> `.tools/` me sirf models/binaries/test screenshots hain — unhe sirf inventory ke liye dekha.

---

## 0. Decisions (user ne confirm kiye, 2026-11-09) aur progress

| Topic | Decision |
|---|---|
| Target hardware | **Raspberry Pi 4, 4 GB RAM** (future). Abhi laptop par demo video |
| Cloud vs offline | **Poora offline**. Internet kam ya bilkul nahi hoga |
| Chatbot | Pehle se bhare hue replies/commands (main cheez) + ek chhota local chatbot fallback |
| Camera / mic | Abhi laptop ka webcam aur mic; baad me external USB |
| Reply language | English / Roman script |
| Voice | Koi bhi natural **Indian** voice |
| Git | Abhi **nahi** (user pehle check karega) |
| Unused files | Hatane ki permission mili |

**Pi 4 ka asar plan par:** Pi 4, Pi 5 se kaafi slow hai. Isliye:
- Common sawaalon ke jawab **canned replies** (pehle se likhe hue, JSON me) se turant milenge. LLM sirf fallback hai, aur Pi par chhota quantized model (Q4) use hoga.
- Whisper **tiny** hi rahega (Pi 4 par base bahut slow hoga).
- `device.profile = pi4` threads 3 aur LLM context 2048 tak limit karta hai, taaki browser/renderer ke liye ek core free rahe.
- Neural poses PC par banenge, Pi par sirf playback.

### Progress
- [x] **Step 0 — Foundation** (cleanup + central config + logging) — *done, user test pending*
- [x] **Step E — Facial expressions** (user request: pehle expressions, phir camera) — *done, user test pending*
- [x] **Feature 1 — Camera eye tracking (1.1–1.5)** — *done, user test pending*. Head-follow (1.6) abhi nahi.
- [x] **Ready-made replies (Step 2.1 ka pehla hissa)** — `config/replies.json`, 24 intents — *done*
- [x] **Hands-free conversation + smart commands (2.3, 2.5, memory)** — *done, user test pending*
  - `frontend/src/hooks/useHandsFree.js`: AudioWorklet mic, adaptive energy VAD (no model), 0.4 s pre-roll, 0.8 s silence = end, 16 kHz WAV → existing `/listen`. Avatar ke bolte/sochte waqt mic pause. Interrupt optional (`allow_interrupt`, default off — laptop speaker par self-trigger ka risk).
  - `backend/app/brain/skills.py`: naam set/get (English, Hinglish, Devanagari → Roman), remember/recall/forget notes (aapko/aapka pronoun swap), news (RSS, offline me saved copy), maths. `memory.py` (per-avatar `memory.json`, atomic), `translit.py`, `news.py`. Order: skills → ready replies → LLM (naam + notes LLM prompt me bhi).
  - Camera par koi aaye (20 s door rehne ke baad) aur hands-free on ho → avatar khud greet karta hai; naam na pata ho to poochta hai. `POST /avatar/{id}/greet`, `GET /avatar/{id}/memory`, `POST /avatar/{id}/memory/forget`.
  - STT: Whisper Hindi ko Urdu script me likhe to Hindi ke saath dobara transcribe.
  - [ ] Barge-in (2.6) sirf optional; Indian voice (Piper, Step 2.2) baaki.
- [x] **Samajh + zinda dikhna (user feedback ke baad)** — *done, user test pending*
  - Problem mila (log se): Whisper tiny bhasha galat pehchaanta tha (en 39%, **es** 26%) → transcript bakwaas. Ab: `stt.language = "hi"` (Hindi + Hinglish + English shabd, auto-detect ke ~1.8 s bhi bache), PC par **Whisper base** (Pi 4 par tiny, apne aap), `hint_words` + yaad naam Whisper ko context ke roop me ("Arjan" → "Arjun", confidence −0.47 → −0.29), "Thank you" jaise hallucination filter, bahut kam confidence wale segment drop.
  - Is laptop par (4 logical CPU) base ~2.7 s fixed cost per sentence (Whisper ki 30 s window); options se farq nahi padta, isliye filler se dhaka.
  - Naam: adhoora "mera naam…" → "Haan ji, aapka naam?"; naam ka sawaal beech ki baat ke baad bhi 90 s khula; "nahi pata"/"kya" jaise shabd naam nahi bante.
  - Zinda dikhna: `animation/LifeMotion.js` — listening (aage jhukna, brows), thinking (nazar upar-side, frown, sir tedha), speaking (awaaz ke saath head dip, naye vaakya par brows), idle (saans/sway). Poori photo par max ~1° rotation + 4% zoom; face warp nahi. Pause idle par band.
  - "Hmm / Achha / Ek second" filler jab jawab 1.4 s me na aaye; TTS cache (same text = same WAV, turant) + TTS lock par 8 s intezaar taaki filler ke baad jawab fail na ho.
  - VAD: "chup" ab aapki awaaz ke peak ke hisaab se (shor me 15 s atakna band). Echo-cancel sirf interrupt mode me — Windows "communications ducking" (baaki awaaz 80% dheemi) se bachne ke liye.
- [x] **Full-screen UI + natural Hindi voice (Step 2.2)** — *done, user test pending*
  - UI: frame poori screen; right-top chhoti rail (☰ + 🎙/👁/🔊 status lights, error par laal dot); baaki sab (photo, expressions, conversation, speak, settings) slide-in drawer me. Drawer sirf chhupta hai, unmount nahi — hands-free/camera chalte rehte hain. Esc / bahar click se band. Mouth-debug sirf `?debug=1`. `frontend/src/layout.css`.
  - Voice: **Piper TTS** (`piper-tts` 1.3.0, offline, Windows + Pi) + `hi_IN-priyamvada-medium` (female, default) / `hi_IN-pratham-medium` (male) in `.tools/models/piper/`. ~0.2× real-time is laptop par. SAPI fallback (Windows).
  - Measured (phonemes): Roman Hinglish ko Hindi voice English uchcharan me padhti hai → isliye Hindi/Hinglish jawab ab **Devanagari** (replies.json, skills, greeting, fillers, LLM prompt). English sawaal → English jawab (Indian lehje me).
  - `brain/style.py`: female persona ke liye kriya (करती हूँ, रखूँगी); Hindi time/date ("रात के 9 बजकर 15 मिनट", "सोमवार"). Naam ka Devanagari roop bhi yaad (`user_name_native`). Hindi news feed Hindi baat-cheet ke liye.
  - Lip-sync: Devanagari visemes (म/ब/प band hoth, आ khula, स/श, ल…).
  - Vision bug fix: stream ka start-up `enabled:false` "settings me band" samjha jaata tha → ab alag `disabled` flag.
- [x] **105 ready-made sawaal-jawab + start par naam poochhna** — *done, user test pending*
  - `config/replies.json`: 24 → 105 intents, 1036 patterns (English / Hinglish / Devanagari), jawab English + Devanagari. Topics: avatar ke baare me, pasand-naapasand, fun (kahani, paheli, shayari, fact), feelings & care (bore, gussa, darr, bimaar, neend), daily life (ghar aaya, bahar ja raha, dawai, khana, exercise), tyohaar, general knowledge (rajdhani, rashtriya pashu/pakshi/phool, Gandhi ji, grah, chaand, Everest, Ganga, 15 August, 26 January).
  - Check script: har pattern apne jawab tak pahunchta hai (0 mismatch); "ek achhi khabar hai" ab news skill nahi kholta.
  - Matcher 578 ms → 30 ms per message (length bound + quick_ratio pre-filter) — Pi 4 ke liye zaroori.
  - **Awaaz galat samajhne ka asli kaaran (log + test se):** Whisper ko diya gaya hint-vaakya ("Namaste… Aap kaise ho? Kya chal raha hai?") shor ya saaf-na-sunayi-dene wali awaaz par transcript me copy ho jaata tha → avatar "kaise ho / kya chal raha hai" ka jawab deta rehta tha (session me 5× `whats_up`). Fix: sentence prompt hataya, ab sirf **hotwords** (naam + `hint_words`) — shor par khaali transcript, "Arjun" spelling sahi. Whisper unsure (`min_confidence`, default −0.8) aur kuch match nahi → "माफ़ कीजिए… फिर से बोलिए?" (LLM ko andaaza nahi lagane dete). `log_transcripts` (opt-in) se terminal me "Heard: …".
  - **"Speech recognition is busy" (log se):** VAD shor par baar-baar trigger ho raha tha (ek ke baad ek ~15 recordings, sab "no speech"); har ek par Whisper ~3 s busy → asli baat chhoot jaati thi, beech me nayi recording → 503. Fix: VAD sakht (≥250 ms saaf awaaz + peak ≥ 5× shor, warna Whisper ko bheja hi nahi jaata), "no speech" par shor-level apne aap badhta hai, "no speech" chupchaap (koi error nahi), cooldown 0.9 s, greeting ke dauraan mic band, backend Whisper busy ho to 20 s tak intezaar (error nahi). Naam clause-wise: "My name is Arjun, Laila Arjun" → "Arjun". Piper (~7 s) aur Whisper (~5 s) start-up par background me pre-load.
  - Start: `[conversation] start_on_load` + `ask_name_on_start`. Face tayyar hote hi hands-free on + "आपका नाम क्या है?"; jawab me naam save. Laptop Chrome pehle ek tap maangta hai ("Tap to start" overlay), Pi kiosk (autoplay allowed) me apne aap — headless Chrome me auto-start + name save verify kiya.
- [ ] Feature 2 — Voice conversation (2.1 → 2.6)
- [ ] Step P — Raspberry Pi port

**Step 0 me kya hua:**
- Hataye: `NeuralSettings.jsx`, `NeuralVideo.jsx`, `useNeuralAvatar.js`, `BreathingLayer.js`, purane `server*.log` files.
- Root ki 3 photos **delete nahi ki**, `samples/` folder me move ki (ek personal WhatsApp photo ho sakti thi).
- Naya `config/settings.toml` (saari settings), `config/.env.example` (future secrets), `backend/app/settings.py` (loader + validation + Pi auto-detect), `backend/app/logging_setup.py`, `GET /config` (sirf non-secret settings), `backend/tests/test_settings.py` (8 tests).
- LLM, STT, persona aur TTS speed ab config file se aate hain. Purane `LIVING_*` env vars ab bhi kaam karte hain.
- Linux par llama.cpp ka default binary naam ab `llama-server` hai (`.exe` sirf Windows par).

**Step E me kya hua (expressions):**
- **Bug fix "Neural engine is busy"**: page reload ya doosra tab same photo ka atlas maange to ab chal rahe job se jud jaata hai (`engine_manager.py`, `watchers` count). Job tabhi cancel hota hai jab koi tab use nahi dekh raha. Agar engine kisi *doosri* photo me busy ho to page error ki jagah "waiting" dikha kar khud retry karta hai (`usePreparedAvatar.js`).
- **LivePortrait eyebrow control** vendored (`expression.py: update_delta_new_eyebrow`, upstream se), `MotionControl` me `eyebrow` aur `gaze_y`. Smile ki limit 0.6 → 1.0 (0.6 par sirf hoth hilte the, 1.0 par cheeks aur aankhon ki sikudan bhi aati hai).
- **Atlas v4** (`atlas.py`): nayi poses `happy` (.5, 1.0), `laugh` (smile 1.0 + mouth .15/.30/.45 + halki aankh sikudan), `brow` (+6, +12), `frown` (−8), `up`/`down` gaze (camera step ke liye). Values asli portrait par contact sheets render karke chuni gayin. Eyebrow mask aankh ke centre se upar rukta hai taaki iris double na dikhe. Purani poses reuse hoti hain → upgrade me sirf ~10 nayi poses render hoti hain.
- **Frontend**: Laugh ab 3–4 "ha-ha" bursts me hota hai jo dheere halke hote hain (`laughOpening`), aur hansi ke baad smile dheere utarti hai. Smile button full face smile use karta hai. Naya **Eyebrows** button. Bolte waqt beech-beech me eyebrows halki uthti hain. Idle me kabhi-kabhi halki muskaan aati hai, taaki chehra frozen na lage. Purane (v3) atlas wale avatars pehle jaisa hi chalte hain.
- Lightweight renderer me koi behaviour change nahi.

**Camera eye tracking me kya hua:**
- `backend/app/vision/`: `camera.py` (Windows DirectShow / Linux V4L2, camera na mile to 5→60 s backoff, crash nahi), `face_tracker.py` (YuNet ONNX 232 KB in `.tools/models/yunet/`, na ho to OpenCV Haar fallback; sabse bada chehra; presence hysteresis 0.3 s aana / 2 s jaana), `service.py` (ek background thread; camera sirf tab chalta hai jab browser stream dekh raha ho, 10 s baad band), `routes.py` (`GET /vision/stream` Server-Sent Events, `GET /vision/status`), `check.py` (terminal test).
- Frames memory me process hote hain, kahin save ya bheje nahi jaate.
- Frontend: `hooks/useGazeTarget.js` (EventSource), `animation/GazeController.js` (smooth pursuit, saccade + kabhi blink, micro-jitter, kabhi-kabhi nazar hatana, koi na ho to dheere wander). Neural mode me atlas ki left/right/up/down eye poses, Lightweight me existing eye warp. Page par status + TURN ON/OFF button (browser me yaad rehta hai).
- Direction measured: `left` pose me iris screen-left jaati hai; `vision.mirror = true` se user apne right jaye to avatar screen-right (user ki taraf) dekhta hai. Ulta lage to `mirror = false`.

**Ready-made replies me kya hua:**
- `backend/app/brain/canned_replies.py` + `config/replies.json`. English / Hinglish (Roman) / Hindi (Devanagari) patterns. English input → English jawab, Hindi/Hinglish → Hinglish (Roman) jawab, taaki abhi ki English voice padh sake.
- Spelling variations (achha/acha, dhanyawad/dhanyavaad, हूँ/हूं) aur fuzzy match. Do baatein ek saath ("Hi, how are you") → dono jawab. Lamba/alag sawaal → local AI. `{name}`, `{time}`, `{date}`, `{day}` placeholders. File app chalte hue edit ho sakti hai; galat JSON par pichhla version chalta rehta hai.
- LLM band ho (`[llm] enabled = false`) to match na hone par "samjha nahi" fallback.

---

## 1. Short summary (2 minute version)

Project aapki expectation se **kaafi aage** hai. Sirf "photo → avatar → TTS → lip-sync" nahi, balki Phase 6 tak ka kaam already hua hai:

- Photo upload → face/eye/mouth detection (OpenCV) ✅
- Do renderers: **Lightweight canvas warp** aur **"Prepared neural face"** (LivePortrait se 21 poses ek baar pre-render, phir browser me 60 FPS blend) ✅
- Text-to-speech (Windows SAPI) + amplitude + viseme based lip-sync ✅
- Blink, smile, laugh, look-left/right ✅
- **Push-to-talk voice conversation already hai**: mic record → Whisper Tiny (local) → Qwen3-0.6B via llama.cpp (local) → sentence-by-sentence TTS → lip-sync ✅
- Short-term memory (last 4 turns, in-memory) ✅

Lekin teen badi problems hain:
1. **TTS sirf Windows par chalta hai** (SAPI/PowerShell). Raspberry Pi (Linux) par voice bilkul nahi chalegi.
2. **Hindi voice nahi hai** — machine par sirf English voices (Hazel/David/Zira) hain. Hindi text English voice se bolega ya fail hoga.
3. **Camera ka koi code nahi hai**, aur conversation **hands-free nahi** hai (TALK / FINISH button dabana padta hai, VAD nahi, interruption nahi).

Git repo **nahi** hai (`.gitignore` hai, par `git init` nahi hua).

---

## 2. Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite 6 + Tailwind 4, plain JavaScript (no TypeScript). Canvas 2D rendering, Web Audio API |
| Backend | Python 3.11, FastAPI 0.115 + Uvicorn, OpenCV-headless 4.11, NumPy |
| Face detection | OpenCV Haar cascades (face + eye). Mouth position *estimate* (dense landmarks nahi) |
| Neural animation | LivePortrait (selected modules vendored in `backend/app/vendor/liveportrait`), PyTorch 2.6 CPU, alag venv `.tools/neural-venv`, ~520 MB weights |
| TTS | `pyttsx3` (SAPI5) in a subprocess; fallback PowerShell `System.Speech` — **dono Windows-only** |
| STT | `faster-whisper` 1.2.1, Whisper **Tiny** multilingual, INT8, CPU (model `.tools/models/faster-whisper-tiny`, 78 MB) |
| LLM | `llama.cpp` server (`llama-server.exe`, Windows build b11146) + **Qwen3-0.6B Q8_0** GGUF (640 MB), port 8091 |
| Audio decode | PyAV (faster-whisper ke saath aata hai) |
| Tests | Python `unittest` (backend), Playwright + Chrome scripts (`frontend/tests/*.cjs`) |
| Config | Sirf `backend/app/config.py` (paths) + kuch `LIVING_*` environment variables. Ek central config file **nahi** hai |

---

## 3. Folder structure (important parts)

```text
backend/
  app/main.py                     FastAPI app: /health, /avatar/upload, /avatar/{id}, /speak, /audio
  app/config.py                   Paths + upload limit (bas itna hi)
  app/imaging.py                  Image validate/normalize + face detect
  app/services/
    face_landmarks.py             Haar eye detection + mouth estimate
    avatar_store.py               avatar_data/<id>/avatar.json save/read
    tts_service.py                TTS (Windows SAPI subprocess + WAV validation)   ← speech/ yahan plug hoga
    tts_worker.py, tts_fallback.ps1
    conversation_routes.py        /listen (STT), /conversation (LLM stream NDJSON), cancel/clear/unload
    speech_recognition/           STT provider interface + faster-whisper            ← audio/ yahan plug hoga
    local_ai/                     LLM provider interface, llama.cpp manager,
                                  prompt_builder, personality, conversation memory  ← brain/ yahan plug hoga
    neural_avatar/                LivePortrait worker process, atlas (pose bank), routes
  app/vendor/liveportrait/        Copied LivePortrait modules (+ licenses)
  scripts/                        setup_conversation.py, benchmarks
  tests/                          unittest files
frontend/
  src/main.jsx                    Poora page/App (upload, frame, panels)
  src/components/AvatarViewer.jsx Canvas + PortraitEngine lifecycle
  src/animation/PortraitEngine.js Main render loop (state machine, blink, draw)        ← gaze yahan plug hoga
  src/animation/PreparedPortrait.js  Neural pose atlas blending (mouth/blink/look)    ← gaze poses yahan
  src/animation/IdleBehaviorController.js  Random idle gaze/tilt/brow events
  src/animation/visemeTimeline.js, visemeEngine.js, MouthCompositor.js  Lip-sync
  src/hooks/useAvatarSpeech.js    /speak call, WAV play, analyser → mouth motion      ← lip-sync entry point
  src/hooks/useConversation.js    STT → LLM stream → sentence queue → speak
  src/hooks/useMicrophone.js      MediaRecorder push-to-talk
  src/components/ConversationPanel.jsx, SpeechPanel.jsx, NeuralControls.jsx ...
avatar_data/<id>/                 original.jpg, avatar.json, audio/*.wav, neural/*.npz
avatar_data/neural_atlases/       Prepared pose atlas PNG (6–10 MB each) + JSON
uploads/                          Phase-1 compatibility image copies
.tools/                           Portable Python, llama.cpp exe, models, neural venv, test screenshots
```

---

## 4. Current pipeline — step by step

### 4.1 Photo → Avatar
1. Browser `POST /avatar/upload` (JPG/PNG ≤10 MB).
2. `imaging.process_image`: decode, EXIF rotate, longest edge ≤1600 px, JPEG normalize.
3. Haar cascade se sabse bada face. `face_landmarks.extract_landmarks`: do eyes (Haar), mouth position **estimate**.
4. `avatar_store.create_avatar`: `avatar_data/<uuid>/original.jpg` + `avatar.json` (face_box, landmarks, status).
5. Agar eyes nahi mile → avatar static rehta hai (warning).

### 4.2 Avatar → Animation (2 modes)
- **Lightweight (`lightweight`)**: `PortraitEngine` face patch (≤280 px) par per-pixel warp karta hai — blink, smile, look, mouth (procedural teeth/tongue `MouthCompositor`).
- **Prepared neural face (`neural-live`, DEFAULT)**: `usePreparedAvatar` backend se atlas maangta hai → backend ka neural worker (alag Python process, PyTorch) LivePortrait se **21 poses** render karta hai (mouth ×5, round ×4, wide ×4, blink ×8, smile ×2, **look left/right ×1 each**). Pehli baar ~4–5 minute (i5 CPU). Phir browser sirf `drawImage` se poses blend karta hai → ~60 FPS, ~0.6 ms/frame.
- Blink: 3–7 sec random, 180 ms (SadTalker profile). Idle: random gaze/tilt events.

### 4.3 Text → Speech → Lip-sync
1. `useAvatarSpeech.speak(text)` → `POST /avatar/{id}/speak`.
2. `tts_service.generate_speech`: `tts_worker.py` subprocess (pyttsx3/SAPI5) WAV banata hai; fail ho to PowerShell fallback. WAV validate hota hai. Ek waqt me sirf ek synthesis (lock → 429).
3. Browser WAV fetch → `decodeAudioData` → `AnalyserNode` → speakers.
4. Har frame: RMS amplitude → `mouthOpen`; `visemeTimeline` (English spelling heuristics) se mouth shape; `PortraitEngine` draw karta hai.

### 4.4 Voice conversation (already exists, push-to-talk)
1. `useMicrophone`: TALK dabao → MediaRecorder (echoCancellation on) → FINISH → Blob.
2. `POST /listen` → PyAV 16 kHz decode → faster-whisper Tiny (`task=transcribe`, language auto/en/hi).
3. `POST /conversation` → `prompt_builder` (generic system prompt + last 4 turns) → llama.cpp stream → backend sentences me todta hai → NDJSON `chunk` events.
4. Browser har sentence ko queue karke `speech.speak()` se bulwata hai (existing lip-sync reuse).
5. STOP → AbortController + `/conversation/cancel` → sab band. **Yeh stop mechanism interruption ke liye perfect base hai.**

Measured (i5 PC, `conversation_benchmark.json`): STT 1.2–2.7 s, LLM first token ~1.2–1.4 s (cold start 7.5 s), LLM process RAM ~1.3 GB.

---

## 5. Kya working hai / half-done hai / broken ya unused hai

### ✅ Fully working (Windows PC par)
- Upload, face detect, avatar store, legacy records
- Lightweight renderer + prepared neural pose renderer
- Windows English TTS + amplitude/viseme lip-sync, Stop
- Blink, smile, laugh, look buttons, idle motion
- Push-to-talk conversation (Whisper Tiny + Qwen3-0.6B), streaming, cancel, 4-turn memory
- Backend unit tests (~42) aur Playwright browser tests

### 🟡 Half-done / weak
- **Hindi/Hinglish**: STT me "hi" option hai, par Whisper **Tiny** Hinglish me kamzor hai; Hindi **voice nahi** hai; LLM 0.6B Hindi me bahut weak (benchmark me sawal ko hi repeat kar diya: "नमस्ते, आप कैसे हैं?" → same).
- **Lip-sync for Hindi**: `visemeTimeline.textToVisemes` sirf a–z samajhta hai; Devanagari ka har akshar `OPEN` ban jaata hai. Amplitude se mouth hilta hai, par shapes generic.
- **Persona**: sirf env vars `LIVING_AVATAR_NAME`, `LIVING_SPEAKING_STYLE`. Prompt bolta hai "You are not a real person" — family-member/companion persona ka koi system nahi. Per-avatar persona store nahi.
- **Memory**: sirf RAM me, 4 turns, 1 ghante baad expire. Long-term memory nahi.
- **Gaze in neural mode**: sirf 2 poses (left/right, horizontal). Up/down nahi. `IdleBehaviorController` ka idle gaze **neural-live mode me apply hi nahi hota** (sirf lightweight mode me `secondary.gazeX` use hota hai). Eyebrow movement bhi lightweight-only aur abhi `browLift = 0` set hai (disable).
- **Latency**: sentence TTS serial hai — sentence 1 bolne ke baad hi sentence 2 ka TTS shuru hota hai (prefetch nahi).
- **Config**: settings bikhre hue — `config.py`, env vars, hard-coded values (port 8091, threads 4, 175 wpm, timeouts).

### 🔴 Broken / not portable / unused
- **TTS on Linux/Pi**: `generate_speech` me `if sys.platform != "win32": raise 503` — Pi par speech bilkul band.
- **llama.cpp**: `.exe` path hard-coded default; Pi ke liye ARM build chahiye.
- **Unused frontend files** (koi import nahi karta): `components/NeuralSettings.jsx`, `components/NeuralVideo.jsx`, `hooks/useNeuralAvatar.js`, `animation/BreathingLayer.js`.
- Purane logs repo root/backend me pade hain (`backend/*.log`, `frontend/server.*.log`), aur 3 random JPEG root me (`dfb.jpeg`, `fnfnfnnnnnn.jpeg`, WhatsApp image). Harmful nahi, bas clutter.
- **Camera**: koi code nahi.
- **Hands-free / VAD / barge-in**: nahi hai.
- `avatar_data/` me ~25 test avatars + audio pade hain (gitignored).

---

## 6. New features kahan plug honge (key files/functions)

### Feature 1: Camera eye/gaze tracking
| Kya | Kahan |
|---|---|
| Camera capture + face detection (naya) | `backend/app/vision/` (naya package) — alag thread/process |
| Gaze target browser tak bhejna | Naya WebSocket route, `backend/app/vision/routes.py`, `main.py` me register |
| Browser me receive | Naya `frontend/src/hooks/useGazeTarget.js` |
| Smooth eye motion, saccades, idle | Naya `frontend/src/animation/GazeController.js`; `IdleBehaviorController.update()` ke saath merge |
| Render | `PortraitEngine.draw()` — abhi `pose.look` sirf LOOK_LEFT/RIGHT button se aata hai; yahan gaze controller ka output jayega. Neural mode: `PreparedPortrait.draw()` → `drawGroup('left'/'right')` ko 2D gaze blend me badalna |
| Zyada gaze poses | `backend/app/services/neural_avatar/atlas.py` `POSES` list (abhi `gaze_x=±6` only). `model_loader.render()` already `update_delta_new_eyeball_direction(gaze_x, 0, …)` call karta hai — doosra argument vertical hai, toh **up/down asaani se add ho sakta hai** |
| Head follow (optional) | `MotionControl` me `yaw/pitch` fields already hain, par poore face ke poses chahiye — mehenga (section 8 dekho) |

### Feature 2: Automatic voice conversation
| Kya | Kahan |
|---|---|
| Mic + VAD (speech start/stop) | Option A: `frontend/src/hooks/useMicrophone.js` ko VAD wala banana. Option B: `backend/app/audio/` (Python mic capture) |
| STT | `speech_recognition/stt_manager.py` → `backend/app/audio/stt/` me move + provider choice |
| LLM + persona + memory | `local_ai/` → `backend/app/brain/` (`prompt_builder.build_prompt`, `personality.Personality`, `conversation_manager`, `llm_manager`) |
| TTS → existing lip-sync | `tts_service.generate_speech` → `backend/app/speech/` provider (Piper/SAPI/cloud). `/speak` API **same rahega**, toh `useAvatarSpeech` aur lip-sync bina change ke chalenge |
| Conversation loop + interrupt | `frontend/src/hooks/useConversation.js` (`request`, `stop`) — state machine add hogi; `stop()` already sab cancel karta hai |
| Hindi visemes | `frontend/src/animation/visemeTimeline.js` `textToVisemes` me Devanagari mapping |
| Central settings | Naya `config/settings.yaml` + `.env` (secrets) + `backend/app/settings.py` |

---

## 7. Raspberry Pi risks

Assumption: Raspberry Pi 5 (4 ya 8 GB), 64-bit Raspberry Pi OS, Chromium kiosk mode me frontend. (Pi model abhi confirm nahi — section 10 ke questions dekho.) Neeche ke Pi numbers **estimate** hain, measured nahi.

| Part | Risk | Kyun / kya karein |
|---|---|---|
| **TTS** | 🔴 Blocker | Windows-only. Pi ke liye Piper (offline) ya cloud TTS lagana hi padega |
| **LivePortrait atlas preparation** | 🔴 Heavy | PyTorch + 520 MB weights, peak ~1.1 GB RAM, i5 par ~20 s/pose. Pi par kai guna slow (shayad 30–60+ min ek photo ke liye). **Recommendation: atlas PC par banao, Pi par sirf PNG atlas copy karo.** Playback khud halka hai |
| **LLM local (Qwen3-0.6B)** | 🟠 | Pi 5 par chal jayega (~1.3 GB RAM), par slow aur Hindi/Hinglish quality kharab. Bada model (1.5B–3B) Pi par bahut slow hoga. Achhi Hinglish ke liye cloud LLM behtar |
| **STT local (Whisper Tiny)** | 🟠 | Pi 5 par chalega (shayad 2–5 s per sentence). Hinglish accuracy kam. `base` model behtar par ~2× slow |
| **RAM total** | 🟠 | Chromium (~400–700 MB) + backend + Whisper (~300 MB) + LLM (~1.3 GB) + camera. **4 GB tight, 8 GB recommended** agar sab offline chalana hai |
| **Camera face detection** | 🟢 | YuNet/Haar at 320×240, 10–15 FPS — Pi 5 par halka |
| **Render (neural-live mode)** | 🟢 | Sirf `drawImage` blending — Pi par bhi theek. Lightweight mode ka per-pixel warp heavy hai, Pi par slow ho sakta hai |
| **Atlas PNG size** | 🟢/🟠 | 6–10 MB PNG, browser me decode ~100+ MB GPU/RAM. OK |
| **Thermals** | 🟠 | Lagatar camera + STT + LLM = CPU garam. Pi 5 ke liye active cooler zaroori |
| **Echo / self-hearing** | 🟠 | Speaker aur mic ek hi frame me → avatar apni awaaz sun sakta hai. Browser ka echoCancellation help karta hai; hardware AEC wala speakerphone best |
| **Windows-specific code** | 🟠 | `.exe` paths, `CREATE_NO_WINDOW`, PowerShell scripts, portable Python — Linux run scripts banane padenge |

---

## 8. Implementation plan

Har step chhota hai, alag test hoga, aur aapke OK ke baad hi aage badhenge. Har working step par git commit (agar git init approve ho).

### Step 0 — Foundation (dono features se pehle)
- **0.1 Git**: `git init` + baseline commit (sirf source; models/avatars already gitignored).
- **0.2 Central config**: `config/settings.yaml` (non-secret: camera index, language, model choices, providers) + `.env` / `.env.example` (API keys) + `backend/app/settings.py` loader. Existing `LIVING_*` env vars backward-compatible rahenge. `GET /config` endpoint frontend ke liye (secrets kabhi nahi bhejega).
- **0.3 Logging**: ek common logger format (`backend/app/logging_setup.py`).
- Files: naye `config/`, `backend/app/settings.py`; modify `config.py`, `main.py`, `llm_manager.py`, `stt_manager.py`, `personality.py` (sirf settings padhne ke liye).
- **Test**: saare existing backend tests pass; `GET /config` me settings dikhe, koi key nahi; app pehle jaisa chale.

### Feature 1 — Camera eye/gaze tracking

**1.1 Camera capture (`backend/app/vision/camera.py`)**
- Library: OpenCV `VideoCapture` (USB webcam, Windows + Pi). Pi Camera Module ke liye `picamera2` backend (sirf Pi par). 320×240 @ 15 FPS, apne thread me.
- No camera → warning log, `vision.available = false`, app normal chalega.
- **Test**: `python -m app.vision.check` → FPS print kare; camera unplug karke chalao → crash nahi.

**1.2 Face detection + target (`backend/app/vision/face_tracker.py`)**
- Recommended: **OpenCV YuNet** (`cv2.FaceDetectorYN`, ~230 KB ONNX, offline, OpenCV already installed, Pi par fast). Alternatives: MediaPipe Face Detection (accurate, Pi 64-bit par pip available), Haar (already used, sabse fast par jittery). Cloud ki zaroorat nahi.
- Sabse bada/paas wala face choose, normalized `(x, y, size)`, presence with hysteresis (aane ke ~0.3 s baad "present", jaane ke ~2 s baad "absent").
- **Test**: check script me face ke saath x/y values change hon; haath se chehra dhako → absent.

**1.3 WebSocket bridge**
- `backend/app/vision/routes.py`: `/ws/vision` ~15 Hz `{present, x, y, size, ts}`. Frontend `hooks/useGazeTarget.js` (auto-reconnect, camera nahi to silently off).
- **Test**: browser console/debug overlay me live values.

**1.4 Natural gaze controller (`frontend/src/animation/GazeController.js`)**
- Camera coords → eye direction (mirror + calibration offsets from config).
- Critically-damped smoothing + **saccades** (bada move = tez jump, chhota = smooth), **micro-saccades/drift** taaki kabhi frozen na lage, kabhi-kabhi thoda nazar hatana, bade gaze shift par blink.
- **Idle mode** (koi nahi): dheere wander, slow blinks — existing `IdleBehaviorController` se merge.
- Lightweight mode me existing `secondary.gazeX/Y` path wire karna.
- **Test**: debug overlay me gaze values; camera ke saamne left-right chalo → aankhen follow karein; hat jao → idle.

**1.5 Neural gaze poses (atlas v4)**
- `atlas.py` me gaze poses add: x ∈ {−6, −3, +3, +6}, y ∈ {−4, +4} (+ diagonals optional). `MotionControl` me `gaze_y`. Existing poses reuse hote hain → sirf ~6–8 nayi poses (~2–3 min PC par).
- `PreparedPortrait`: 2D gaze blending. Double-iris se bachne ke liye nearest-pose + chhota cross-fade (jaise blink me already kiya gaya hai).
- **Test**: neural mode me aankhen 8 directions me jayein, iris double na dikhe; existing mouth/blink tests pass.

**1.6 (Optional) Head follow**
- Sach me head ghumana = poore face ki poses × mouth combos → bahut mehenga (Pi par aur bhi). Sasta option: poore canvas ka bahut halka (1–2°) tilt/parallax. Pehle 1.5 dekh ke decide karenge.

### Feature 2 — Automatic voice conversation

**2.1 Brain: persona + memory (`backend/app/brain/`)**
- `local_ai/` ko `brain/` me move (purane imports shim se chalte rahenge).
- Per-avatar `avatar_data/<id>/persona.json`: naam, relation (e.g. "Nani"), bolne ka style, preferred language/script, kuch facts. Simple API + UI form.
- Prompt: Hindi/English/Hinglish rules (user jis language me bole, usi me jawab; Hinglish Roman script me).
- Memory: existing short-term + optional rolling summary (disk par, per avatar).
- LLM providers (config se select): `llamacpp` (offline, existing) **ya** cloud (Claude / OpenAI / Gemini — ek choose karna hai). Cloud fail → local fallback.
- **Test**: unit tests; typed chat se persona naam/tone check; Hinglish sawaal → Hinglish jawab.

**2.2 Speech: cross-platform TTS (`backend/app/speech/`)**
- Provider interface; `/speak` API same → **lip-sync code bina change**.
- Offline: **Piper** (Linux/Pi par fast, Hindi voices available, en_IN voice bhi) ; Windows SAPI provider rehega.
- Cloud options: Azure (hi-IN Neural voices, Hinglish achha), Google Cloud TTS, ElevenLabs (premium), Sarvam AI (Indian languages focus).
- Language routing: Devanagari → Hindi voice; Roman Hinglish → Indian-English/Hindi voice.
- `visemeTimeline.js`: Devanagari → viseme mapping (म/ब/प → M/B/P, आ → A, etc.).
- **Next-sentence TTS prefetch** (latency kam).
- **Test**: "नमस्ते, आप कैसे हैं?", "Hello, how are you?", "Aaj ka din kaisa tha?" — teeno bolein aur mouth sync ho.

**2.3 Hands-free listening (VAD)**
- **Option A (recommended)**: browser me mic + **Silero VAD** (ONNX, `@ricky0123/vad-web`, offline bundle). Fayda: browser ka built-in **echo cancellation** → interruption possible, existing `useMicrophone`/`/listen` reuse.
- **Option B**: `backend/app/audio/` Python me `sounddevice` + Silero VAD (onnxruntime). Fayda: sab Python me; Nuksaan: avatar ki apni awaaz se self-trigger, AEC ke liye hardware speakerphone chahiye.
- Speech start → recording, ~700 ms silence → end → auto `/listen`.
- **Test**: bina button dabaaye bolo → transcript aaye; khamosh kamre me false triggers na hon.

**2.4 STT for Hinglish**
- Offline: faster-whisper **base** ya **small** INT8 (configurable; Pi par base max). Cloud: Sarvam Saarika (Hinglish strong), Deepgram, Google, OpenAI.
- **Test**: 10 recorded Hinglish sentences par accuracy compare (Tiny vs chosen).

**2.5 Conversation state machine (`useConversation.js`)**
- `IDLE → LISTENING → TRANSCRIBING → THINKING → SPEAKING → LISTENING`.
- Camera se link: koi saamne aaye → greeting + listening on; chala jaye → kuch der baad idle/listening off (mic privacy + CPU bachat).
- **Test**: poora loop bina koi button ke 5 turns.

**2.6 Interruption (barge-in)**
- SPEAKING ke dauraan VAD chalu; user ~300 ms+ bole → existing `conversation.stop()` → naya turn.
- **Test**: avatar lamba jawab de raha ho, beech me bolo → turant chup ho aur aapki baat sune.

### Step P — Raspberry Pi port (features ke baad ya parallel)
- Linux run scripts, llama.cpp ARM build (agar local LLM), Piper install, Chromium kiosk, `systemd` auto-start, cooling check.
- Atlas PC par banana + copy karne ki script.
- **Test**: Pi par boot → frame khud khule → baat-cheet chale; CPU temp/RAM log.

### Future (abhi NAHI banana): Café billing
- Architecture me `brain/` ke andar "tools/skills" ka hook rakhenge (LLM function-calling) taaki baad me `billing/` module alag se plug ho sake. Abhi koi billing code nahi.

---

## 9. Offline vs Cloud — quick comparison

| Part | Offline option | Pi feasibility | Cloud option | Note |
|---|---|---|---|---|
| Face/gaze | YuNet / MediaPipe | ✅ easy | — | Hamesha local rakhna chahiye (privacy, latency) |
| VAD | Silero VAD | ✅ easy | — | Local |
| STT | Whisper tiny/base | 🟡 slow-ish, Hinglish weak | Sarvam / Deepgram / Google / OpenAI | Hinglish ke liye cloud kaafi behtar |
| LLM | Qwen3 0.6B–1.7B (llama.cpp) | 🟡 slow, weak Hindi | Claude / OpenAI / Gemini | Persona quality ke liye cloud bahut behtar |
| TTS | Piper | ✅ fast | Azure / Google / ElevenLabs / Sarvam | Natural Hindi voice ke liye cloud behtar |
| Neural poses | LivePortrait | 🔴 prep bahut slow | — | PC par prepare, Pi par playback |

Recommended: **Hybrid** — camera, VAD, rendering local; STT/LLM/TTS cloud (achhi Hinglish), aur internet na ho to local fallback.

---

## 10. Open questions (Phase 2 se pehle jawab chahiye)

1. Raspberry Pi model aur RAM? (Pi 5 8GB / 4GB / Pi 4 / abhi liya nahi)
2. Offline, cloud ya hybrid?
3. Agar cloud LLM: kaunsa provider (Claude, OpenAI, Gemini)? API key available hai?
4. Camera kaunsa? (USB webcam ya Pi Camera Module) Mic/speaker kaunsa? (USB mic, speakerphone with echo cancellation?)
5. Mic browser me (Option A, recommended) ya Python me (Option B)?
6. Hinglish jawab Roman script me (e.g. "Main theek hoon") ya Devanagari me?
7. Avatar ki awaaz: koi bhi natural Hindi/Indian voice chalegi, ya future me voice cloning chahiye?
8. Git init karke baseline commit karoon?
9. Unused files (`NeuralSettings.jsx`, `NeuralVideo.jsx`, `useNeuralAvatar.js`, `BreathingLayer.js`) aur root ke purane logs/test images hata doon, ya rehne doon?
