import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import './phase2.css';
import './phase3.css';
import './layout.css';
import SpeechPanel from './components/SpeechPanel';
import ConversationPanel from './components/ConversationPanel';
import NeuralControls from './components/NeuralControls';
import { useAvatarSpeech } from './hooks/useAvatarSpeech';
import { usePreparedAvatar } from './hooks/usePreparedAvatar';
import { useGazeTarget } from './hooks/useGazeTarget';
import DigitalFrame from './components/DigitalFrame';
import AvatarViewer from './components/AvatarViewer';
import AvatarControls from './components/AvatarControls';
import AvatarStatus from './components/AvatarStatus';
import CameraPanel from './components/CameraPanel';

function Icon({ kind }) {
  const paths = {
    upload: <><path d="M12 16V3m-5 5 5-5 5 5"/><path d="M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/></>,
    portrait: <><rect x="3" y="2" width="18" height="20" rx="3"/><circle cx="12" cy="9" r="3"/><path d="M6 21v-2a6 6 0 0 1 12 0v2"/></>,
    smile: <><circle cx="12" cy="12" r="9"/><path d="M8 14a4 4 0 0 0 8 0M8 9h.01M16 9h.01"/></>,
    laugh: <><circle cx="12" cy="12" r="9"/><path d="m7 9 2-1 2 1m2 0 2-1 2 1M7 13h10a5 5 0 0 1-10 0Z"/></>,
    speak: <><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8"/></>,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind]}</svg>;
}

// The reply's feeling (from the AI) shows on the face as the avatar starts to answer.
const EXPRESSIONS = { happy: 'SMILE', laugh: 'LAUGH', surprised: 'BROWS', caring: 'SMILE' };

// Turn whatever photo was chosen into an upright JPEG of at most 2048 px. Windows often names
// JPEGs ".jfif", some apps label them image/jpg or image/pjpeg, and phone photos can be 12+ MB,
// 48 MP and stored sideways (EXIF): the browser decodes and rotates them, so all of these work.
const MAX_SIDE = 2048;
async function normalizePhoto(file) {
  if (file.size > 60 * 1024 * 1024) throw new Error('This photo is too large (over 60 MB).');
  let bitmap;
  try { bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' }); }
  catch {
    const heic = /\.(heic|heif)$/i.test(file.name) || /hei[cf]/i.test(file.type);
    throw new Error(heic ? 'iPhone HEIC photos cannot be read here. Please save the photo as JPG and upload again.'
      : 'This file could not be read as a photo. Please choose a JPG or PNG image.');
  }
  const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);  // transparent PNGs get a white background
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .92));
  if (!blob) throw new Error('Could not prepare this photo. Please try another one.');
  return new File([blob], (file.name.replace(/\.[^.]*$/, '') || 'photo') + '.jpg', { type: 'image/jpeg' });
}

function App() {
  const [preview, setPreview] = useState('');
  const [status, setStatus] = useState('idle');
  const [message, setMessage] = useState('Waiting for your portrait');
  const [dragging, setDragging] = useState(false);
  const [filename, setFilename] = useState('');
  const [avatar, setAvatar] = useState(null);
  const speech = useAvatarSpeech(avatar?.avatar_id);
  const conversationControl = useRef(null);
  const [conversationBusy, setConversationBusy] = useState(false);
  const [animationMode, setAnimationMode] = useState('neural-live');
  const prepared = usePreparedAvatar(avatar, animationMode === 'neural-live');
  const [appConfig, setAppConfig] = useState(null);
  const [mood, setMood] = useState('idle');  // listening | thinking | idle (speaking is detected from audio)
  useEffect(() => { fetch('/config').then(r => r.ok ? r.json() : null).then(setAppConfig).catch(() => {}); }, []);
  const [tracking, setTracking] = useState(() => { try { return localStorage.getItem('eyeTracking') !== 'off'; } catch { return true; } });
  const toggleTracking = () => setTracking(value => {
    try { localStorage.setItem('eyeTracking', value ? 'off' : 'on'); } catch { /* storage unavailable */ }
    return !value;
  });
  // The camera runs only while a portrait is shown and tracking is on (it stops ~10 s after).
  // Camera and conversation start only once the face is fully usable (set below from faceReady):
  // during preparation the camera would also slow the neural engine down 2-4x.
  const [faceUsable, setFaceUsable] = useState(false);
  const gaze = useGazeTarget(!!appConfig?.vision?.enabled && tracking && !!avatar?.animation_available && faceUsable);
  const [cameraPanel, setCameraPanel] = useState(() => { try { return localStorage.getItem('cameraPanel') !== 'off'; } catch { return true; } });
  const showCameraPanel = value => {
    setCameraPanel(value);
    try { localStorage.setItem('cameraPanel', value ? 'on' : 'off'); } catch { /* storage unavailable */ }
  };
  // cameraVisible = the camera actually runs (face ready + eye tracking on). The panel itself
  // stays on screen whenever a portrait is loaded, and says why the camera is waiting/off.
  const cameraVisible = !!appConfig?.vision?.enabled && appConfig?.vision?.preview !== false && tracking && !!avatar?.animation_available && faceUsable;
  const cameraSlot = !!appConfig?.vision?.enabled && appConfig?.vision?.preview !== false && !!avatar?.face_detected;
  const cameraWaiting = cameraVisible ? null
    : !tracking ? { text: 'Camera is turned off', action: 'TURN CAMERA ON' }
    : { text: 'कैमरा चेहरा तैयार होते ही चालू होगा · Camera starts when the face is ready' };
  // Like people do, the avatar mirrors a feeling it sees: smiles back, laughs along, raises its
  // brows at surprise (at most every 5 s, never mid-sentence: the engine queues it).
  useEffect(() => {
    if (!cameraVisible) return;
    let lastFeeling = 'neutral', lastAt = 0;
    const MIRROR = { smiling: 'SMILE', laughing: 'SMILE', laughing_hard: 'LAUGH', surprised: 'BROWS' };
    const timer = setInterval(() => {
      const a = gaze.latest.current?.analysis;
      const feeling = a && a.confidence >= .4 ? a.emotion : 'neutral';
      if (feeling !== lastFeeling && MIRROR[feeling] && performance.now() - lastAt > 5000) {
        lastAt = performance.now();
        setAction({ type: MIRROR[feeling], id: Date.now() });
      }
      lastFeeling = feeling;
    }, 400);
    return () => clearInterval(timer);
  }, [cameraVisible]); // eslint-disable-line react-hooks/exhaustive-deps
  // Conversation state + camera for the avatar's human behaviour (SocialBehavior), read per frame.
  const social = useRef({});
  const getSocial = () => {
    const seen = gaze.latest.current;
    return { analysis: seen?.analysis || null, present: !!seen?.present, size: seen?.size || 0, ...social.current };
  };
  // The avatar's voice follows its photo (a man's photo → male voice); the guess can be switched.
  // Kept in its own state so switching never rebuilds the animated face.
  const [voice, setVoice] = useState(null);
  useEffect(() => { setVoice(avatar?.face_detected ? (avatar.voice_gender || avatar.gender || null) : null); }, [avatar]);
  const switchVoice = async () => {
    const next = voice === 'male' ? 'female' : 'male';
    try {
      const response = await fetch(`/avatar/${avatar.avatar_id}/voice`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ gender: next }) });
      if (response.ok) setVoice(next);
    } catch { /* keep the current voice */ }
  };
  const [neuralClip, setNeuralClip] = useState(null);
  const speechPanel = useRef(null);
  const frameElement = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [handsFreeState, setHandsFreeState] = useState('off');
  // Start-up conversation: once per portrait. Browsers only allow sound after a tap, unless
  // they run as a kiosk with autoplay allowed (Raspberry Pi) — then it starts by itself.
  const [startedFor, setStartedFor] = useState(null);
  const [startSignal, setStartSignal] = useState(0);
  const closeButton = useRef(null);
  useEffect(() => {
    if (!menuOpen) return;
    closeButton.current?.focus();
    const onKey = event => { if (event.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);
  const [action, setAction] = useState(null);
  const [animationState, setAnimationState] = useState('IDLE');
  const [animationError, setAnimationError] = useState('');
  const [automatic, setAutomatic] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setAutomatic(!media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => { if (animationError) speech.stop(); }, [animationError, speech.stop]);
  const input = useRef(null);
  const busy = useRef(false);
  const savedRequest = useRef(null);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  // Ready-made avatars (avtars/ folder, prepared on a PC): picked in the menu, and opened by
  // themselves on start (the last one used, else the first) so a kiosk Pi needs no clicks.
  const [library, setLibrary] = useState([]);
  const openAvatar = (avatarId, label = 'Saved portrait') => {
    if (!/^[a-f0-9-]{36}$/.test(avatarId || '') || busy.current) return;
    savedRequest.current?.abort();
    conversationControl.current?.stop(); speech.stop();
    const controller = new AbortController();
    savedRequest.current = controller;
    setPreview(''); setNeuralClip(null); setAction(null); setAnimationError(''); setAnimationMode('neural-live');
    setStatus('processing'); setMessage('Opening your saved portrait…');
    fetch(`/avatar/${avatarId}`, { signal: controller.signal }).then(async response => {
      const result = await response.json();
      if (!response.ok || !result.success) throw new Error('Saved portrait unavailable. Please upload it again.');
      setAvatar(result); setFilename(label);
      try { localStorage.setItem('lastAvatar', avatarId); } catch { /* storage unavailable */ }
      setAnimationState(result.animation_available ? 'LOADING' : 'IDLE');
      setStatus(result.face_detected ? 'ready' : 'no-face'); setMessage(result.message);
    }).catch(error => {
      if (error.name !== 'AbortError') { setStatus('error'); setMessage(error.message); }
    });
  };
  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get('avatar');
    fetch('/avatar/library').then(r => r.ok ? r.json() : { avatars: [] }).catch(() => ({ avatars: [] })).then(({ avatars = [] }) => {
      setLibrary(avatars);
      if (fromUrl) return openAvatar(fromUrl);
      let last = null;
      try { last = localStorage.getItem('lastAvatar'); } catch { /* storage unavailable */ }
      const pick = avatars.find(a => a.avatar_id === last) || avatars[0];
      if (pick) openAvatar(pick.avatar_id, pick.name);
      else if (last) openAvatar(last);
    });
    return () => savedRequest.current?.abort();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(picked) {
    if (!picked || busy.current) return;
    // Any photo the browser can open (JPEG incl. .jfif/.jpe, PNG, WebP…) becomes a clean JPEG.
    const file = await normalizePhoto(picked).catch(error => { setStatus('error'); setMessage(error.message); return null; });
    if (!file) return;
    savedRequest.current?.abort();
    conversationControl.current?.stop(); speech.stop();
    setNeuralClip(null);
    busy.current = true;
    setAvatar(null); setAction(null); setAnimationError(''); setAnimationState('IDLE');
    setPreview(URL.createObjectURL(file)); setFilename(file.name);
    setStatus('processing'); setMessage('Looking for a face…');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000);
    try {
      const body = new FormData(); body.append('file', file);
      const response = await fetch('/avatar/upload', { method: 'POST', body, signal: controller.signal });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.success) throw new Error(typeof result?.detail === 'string' ? result.detail : 'Upload failed. Check that the local backend is running.');
      setAnimationState(result.animation_available ? 'LOADING' : 'IDLE');
      setAvatar(result);
      setStatus(result.face_detected ? 'ready' : 'no-face'); setMessage(result.message);
    } catch (error) {
      setStatus('error');
      setMessage(error.name === 'AbortError' ? 'Processing timed out. Please try a smaller photo.' : error instanceof TypeError ? 'Cannot reach the backend. Start the FastAPI server and try again.' : error.message);
    } finally { clearTimeout(timeout); busy.current = false; }
  }

  const warning = animationError || avatar?.warning || (status === 'error' || status === 'no-face' ? message : '') || prepared.error;
  // The prepared face must belong to THIS photo: right after a new upload the previous photo's
  // face is still in state for a moment, which used to start the conversation too early.
  const atlasReady = !!prepared.atlas && prepared.atlas.avatarId === avatar?.avatar_id;
  const preparing = avatar?.animation_available && animationMode === 'neural-live' && !atlasReady && !prepared.error;
  const faceReady = status === 'ready' && avatar?.animation_available && !animationError
    && (animationMode !== 'neural-live' || atlasReady || !!prepared.error);
  const cameraReady = status === 'ready' && avatar?.animation_available && (animationMode !== 'neural-live' || atlasReady || !!prepared.error);
  useEffect(() => { setFaceUsable(!!cameraReady); }, [cameraReady]);
  useEffect(() => {
    if (prepared.error && animationMode === 'neural-live' && avatar?.animation_available) setAnimationMode('lightweight');
  }, [prepared.error]); // eslint-disable-line react-hooks/exhaustive-deps
  const needsTap = appConfig?.conversation?.start_on_load && faceReady && startedFor !== avatar?.avatar_id;
  const startConversation = () => { setStartedFor(avatar.avatar_id); setStartSignal(n => n + 1); };
  useEffect(() => {
    if (!needsTap) return;
    let allowed = navigator.userActivation?.hasBeenActive;
    if (!allowed) {
      try {  // A kiosk browser with autoplay allowed creates a running AudioContext straight away.
        const Context = window.AudioContext || window.webkitAudioContext;
        const probe = new Context(); allowed = probe.state === 'running'; probe.close().catch(() => {});
      } catch { allowed = false; }
    }
    if (allowed) startConversation();
  }, [needsTap]); // eslint-disable-line react-hooks/exhaustive-deps
  return <div className={`stage text-slate-100 ${cameraSlot && cameraPanel ? 'with-camera' : ''}`}>
    {cameraSlot && (cameraPanel
      ? <CameraPanel latest={gaze.latest} mirror={appConfig?.vision?.mirror ?? true} status={gaze.status} onClose={() => showCameraPanel(false)}
          waiting={cameraWaiting} onEnable={() => { if (!tracking) toggleTracking(); }}/>
      : <button className="cam-toggle" onClick={() => showCameraPanel(true)}>📷 Live camera</button>)}
    <main className="stage-main">
      <DigitalFrame frameRef={frameElement} dragging={dragging} processing={status === 'processing'}
        onDragOver={e => { e.preventDefault(); if (!busy.current) setDragging(true); }}
        onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget)) setDragging(false); }}
        onDrop={e => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files[0]); }}>
        {avatar?.face_detected ? <AvatarViewer key={avatar.avatar_id} avatar={avatar} action={action}
          speechMotion={speech.motion} speechPhase={speech.phase} automatic={automatic} onState={setAnimationState} onError={setAnimationError}
          preparedAtlas={prepared.atlas} renderMode={animationMode}
          gazeTarget={gaze.target} gazeMirror={appConfig?.vision?.mirror ?? true} mood={mood} getSocial={getSocial}
          maxFps={appConfig?.render_fps || 60}/>
          : preview ? <img src={preview} alt="Your uploaded portrait" className="portrait"/>
          : <div className="empty-state"><div className="portrait-symbol"><Icon kind="portrait"/></div><h2>Your story starts here</h2><p>Drop a portrait into the frame<br/>and bring a new presence to life.</p><button className="browse-link" onClick={() => input.current.click()}>Choose a photo <span>&nearr;</span></button><span className="format-hint">JPG, JPEG, JFIF, PNG OR WEBP</span></div>}
        {neuralClip && animationMode === 'neural' && !conversationBusy && speech.phase !== 'speaking' && speech.phase !== 'generating' &&
          <video key={neuralClip} src={neuralClip} className="neural-preview" aria-label="Local neural portrait preview" autoPlay muted playsInline
            onEnded={() => setNeuralClip(null)} onError={() => setNeuralClip(null)}/>}
        {preparing && <div className="frame-pill" role="status" aria-label="Neural preparation pill">
          {prepared.waiting ? 'Waiting for the neural engine…' : `Preparing face · ${Math.round(prepared.progress * 100)}%`}</div>}
        {!preparing && prepared.finishing && atlasReady && <div className="frame-pill subtle" role="status" aria-label="Neural details pill">
          {`Ready · adding details ${Math.round(prepared.progress * 100)}%`}</div>}
        {needsTap && <button className="tap-to-start" onClick={() => { speech.unlock(); startConversation(); }}>
          <span>👆 शुरू करने के लिए टैप करें · Tap to start</span></button>}
      </DigitalFrame>
    </main>
    <input ref={input} type="file" accept="image/*,.jpg,.jpeg,.jfif,.jpe,.png,.webp" className="hidden" aria-label="Upload portrait photo" onChange={e => { upload(e.target.files[0]); e.target.value = ''; }}/>

    {/* Small rail on the right: the menu button plus quiet status lights. */}
    <nav className="side-rail" aria-label="Frame menu">
      <button className="rail-menu" aria-label={menuOpen ? 'Close menu' : 'Open menu'} aria-expanded={menuOpen} aria-controls="frame-drawer"
        onClick={() => setMenuOpen(open => !open)}>
        <span/><span/><span/>{warning && !menuOpen && <i className="rail-alert" aria-label="Needs attention"/>}
      </button>
      <span className={`rail-light ${handsFreeState && handsFreeState !== 'off' ? 'on' : ''} ${mood === 'listening' ? 'pulse' : ''}`} title="Hands-free listening">🎙</span>
      <span className={`rail-light ${gaze.status.present ? 'on' : ''}`} title="Camera: person in front">👁</span>
      <span className={`rail-light ${speech.phase === 'speaking' ? 'on pulse' : ''}`} title="Speaking">🔊</span>
    </nav>
    {menuOpen && <div className="drawer-backdrop" onClick={() => setMenuOpen(false)}/>}

    {/* Everything else lives in the drawer. It is only hidden when closed (never unmounted),
        so hands-free conversation, camera and speech keep running. */}
    <aside id="frame-drawer" className={`drawer ${menuOpen ? 'open' : ''}`} aria-label="Controls" aria-hidden={!menuOpen} inert={!menuOpen}>
      <div className="drawer-head"><h2>LIVING FRAME</h2><button ref={closeButton} aria-label="Close menu" onClick={() => setMenuOpen(false)}>✕</button></div>
      <section className="drawer-section" aria-label="Portrait">
        <h3>Photo</h3>
      {avatar?.animation_available && animationMode === 'neural-live' && <div className="animation-warning" role="status" aria-label="Neural preparation">
        {prepared.atlas ? 'Neural face ready — speech, blinks, smiles, laughs and eyebrows use prepared neural poses.' : prepared.error || prepared.waiting ? prepared.status : `Preparing your neural face · ${Math.round(prepared.progress*100)}%. First preparation can take several minutes; the original photo stays visible.`}
        {prepared.error && <button onClick={prepared.retry}>TRY AGAIN</button>}
      </div>}
      {avatar?.animation_available && appConfig?.vision?.enabled && <div className="animation-warning" role="status" aria-label="Eye tracking">
        {!tracking ? '👁 Eye tracking is off.'
          : !gaze.status.available ? '👁 Eye tracking is disabled in settings.'
          : !gaze.status.connected || !gaze.status.camera ? '👁 Looking for a camera… (the avatar works normally without one)'
          : gaze.status.present ? '👁 Eye tracking on — I can see you.'
          : '👁 Eye tracking on — nobody in front, resting.'}
        <button onClick={toggleTracking}>{tracking ? 'TURN OFF' : 'TURN ON'}</button>
      </div>}
      <AvatarStatus status={status} message={message} avatar={avatar} state={animationState} speechPhase={speech.phase} onStop={() => { conversationControl.current?.stop(); speech.stop(); }}
        live={status === 'ready' && avatar?.animation_available && !animationError && automatic && animationState !== 'LOADING'}
        warning={animationError || avatar?.warning}/>
      {avatar?.face_detected && <div className="animation-warning" role="status" aria-label="Avatar voice">
        {voice === 'male' ? '👨 आवाज़: लड़के वाली (Madhur)' : voice === 'female' ? '👩 आवाज़: लड़की वाली (Swara)' : '🔊 आवाज़: settings वाली'}
        {avatar.gender && !avatar.voice_gender && voice === avatar.gender && <small> · फ़ोटो से पहचानी{avatar.gender_confidence ? ` (${Math.round(avatar.gender_confidence * 100)}%)` : ''}</small>}
        <button onClick={switchVoice}>{voice === 'male' ? 'लड़की वाली करें' : 'लड़के वाली करें'}</button>
      </div>}
      {library.length > 0 && <div className="library-picker" aria-label="Ready-made avatars">
        {library.map(item => <button key={item.avatar_id} title={item.name} aria-label={`Open ${item.name}`}
          className={avatar?.avatar_id === item.avatar_id ? 'active' : ''} onClick={() => openAvatar(item.avatar_id, item.name)}>
          <img src={item.image_url} alt="" loading="lazy"/><span>{item.name}</span></button>)}
      </div>}
      <button className="upload-button flex items-center gap-3" disabled={status === 'processing'} onClick={() => input.current.click()}><Icon kind="upload"/>{status === 'processing' ? 'Processing…' : preview ? 'Change Photo' : 'Upload Photo'}</button>
      <p className="upload-note" title={filename}>{filename || 'A clear, front-facing portrait works best'}</p>
      </section>
      <section className="drawer-section" aria-label="Expressions">
        <h3>Expressions</h3>
      <AvatarControls enabled={status === 'ready' && avatar?.animation_available && !animationError && animationState !== 'LOADING'}
        onSpeak={() => speechPanel.current?.focus()}
        onAction={type => { setNeuralClip(null); setAction({ type, id: Date.now() }); }} state={animationState}
        automatic={automatic} onToggle={() => setAutomatic(value => !value)}/>
      </section>
      <section className="drawer-section" aria-label="Talk">
      <ConversationPanel key={avatar?.avatar_id || 'empty'} avatarId={avatar?.face_detected && faceReady ? avatar.avatar_id : null} speech={speech}
        control={conversationControl} onBusy={setConversationBusy} config={appConfig} personPresent={gaze.status.present} onMood={setMood}
        onHandsFree={setHandsFreeState} startSignal={startSignal}
        camera={cameraVisible ? gaze.latest : null} social={social} avatarGender={voice}
        onExpression={feeling => { social.current.replyEmotion = { name: feeling, at: performance.now() }; const type = EXPRESSIONS[feeling]; if (type) setAction({ type, id: Date.now() }); }}/>
      </section>
      <section className="drawer-section" aria-label="Speak typed text">
      <SpeechPanel ref={speechPanel} avatarId={avatar?.avatar_id} animationState={animationState}
        speech={{ ...speech, stop: () => { conversationControl.current?.stop(); speech.stop(); } }}
        enabled={!conversationBusy && status === 'ready' && avatar?.animation_available && !animationError && animationState !== 'LOADING'}/>
      </section>
      <section className="drawer-section" aria-label="Animation settings">
      <NeuralControls key={'neural-' + (avatar?.avatar_id || 'empty')} avatarId={avatar?.animation_available ? avatar.avatar_id : null}
        busy={conversationBusy || speech.phase === 'speaking' || speech.phase === 'generating'} mode={animationMode} setMode={setAnimationMode} onClip={setNeuralClip}/>
      </section>
      <p className="drawer-foot">Your photos and voice stay on this device.</p>
    </aside>
  </div>;
}

createRoot(document.getElementById('root')).render(<React.StrictMode><App/></React.StrictMode>);
