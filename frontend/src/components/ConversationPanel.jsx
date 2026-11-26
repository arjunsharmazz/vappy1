import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import StatusPanel, { statusKey } from './StatusPanel';
import { useMicrophone } from '../hooks/useMicrophone';
import { useConversation } from '../hooks/useConversation';
import { useHandsFree } from '../hooks/useHandsFree';
import { useFeelingReactions } from '../hooks/useFeelingReactions';
import '../phase6.css';

const labels = { idle: 'LIVE', transcribing: 'PROCESSING SPEECH', thinking: 'THINKING', generating: 'GENERATING VOICE', speaking: 'SPEAKING' };
const handsFreeLabels = { starting: 'STARTING MICROPHONE…', listening: 'LISTENING — JUST SPEAK', hearing: 'HEARING YOU…',
  paused: 'PAUSED — NOBODY IN FRONT', error: 'MICROPHONE ERROR', off: 'LIVE' };
const AWAY_BEFORE_GREETING_MS = 20000;

export default function ConversationPanel({ avatarId, speech, control, onBusy, config, personPresent = false, onMood = () => {}, onHandsFree = () => {}, startSignal = 0, onExpression = () => {}, camera = null, social = null, avatarGender = null }) {
  const settings = config?.conversation || {};
  const [text, setText] = useState('');
  const [clearing, setClearing] = useState(false);
  const [notice, setNotice] = useState('');
  const [handsFree, setHandsFree] = useState(false);
  const conversation = useConversation(avatarId, speech, { onEmotion: onExpression });
  const online = config?.brain === 'online';
  const microphone = useMicrophone((blob, duration) => conversation.request(null, blob, duration));
  const transcript = useRef(null);
  const speaking = speech.phase === 'speaking' || speech.phase === 'generating';
  const busy = conversation.phase !== 'idle' || microphone.recording || microphone.requesting || clearing;
  // Kiosk start-up: settings.toml [conversation] hands_free = true turns listening on by itself.
  useEffect(() => { if (settings.hands_free && avatarId) setHandsFree(true); }, [settings.hands_free, avatarId]);
  // While the avatar greets, the microphone must not record (it would hear the greeting itself).
  const [greeting, setGreeting] = useState(false);
  const greet = async (start = false) => {
    if (!avatarId) return;
    setGreeting(true);
    try {
      const response = await fetch(`/avatar/${avatarId}/greet${start ? '?start=true' : ''}`, { method: 'POST' });
      const data = response.ok ? await response.json() : null;
      if (data?.text) await conversation.announce(data.text);
    } catch { /* the avatar simply stays quiet */ } finally { setGreeting(false); }
  };
  // App start-up (main.jsx sends a signal once the face is ready): start listening and greet,
  // asking for the person's name so it can be saved.
  useEffect(() => {
    if (!startSignal || !avatarId) return;
    microphone.cancel(); speech.unlock(); setHandsFree(true); greet(true);
  }, [startSignal]); // eslint-disable-line react-hooks/exhaustive-deps
  const listening = useHandsFree({
    enabled: handsFree && !!avatarId, busy: busy || speaking || greeting,
    paused: !!settings.listen_only_when_present && !personPresent,
    endSilenceMs: settings.end_silence_ms || 800, allowInterrupt: !!settings.allow_interrupt, device: microphone.device,
    onUtterance: (blob, duration) => conversation.request(null, blob, duration)
      .then(result => { if (result?.noSpeech) listening.falseTrigger(); }),
    onInterrupt: () => conversation.stop(),
  });
  // Greet someone who walks up to the frame (camera), if they were away for a while.
  const wasPresent = useRef(false), awaySince = useRef(0);
  useEffect(() => {
    if (personPresent && !wasPresent.current && handsFree && settings.greet_on_arrival && !busy && !speaking
        && (!awaySince.current || performance.now() - awaySince.current > AWAY_BEFORE_GREETING_MS)) greet();
    if (!personPresent && wasPresent.current) awaySince.current = performance.now();
    wasPresent.current = personPresent;
  }, [personPresent]); // eslint-disable-line react-hooks/exhaustive-deps
  // The avatar notices feelings, gestures and fingers on camera and speaks up by itself whenever
  // nothing else is happening (with or without hands-free listening).
  useFeelingReactions({ latest: camera, enabled: !!camera && !!avatarId && !!config?.vision?.react_to_feelings,
    idle: conversation.phase === 'idle' && !speaking && !greeting && !microphone.recording
      && !['hearing', 'starting'].includes(listening.state),
    onNotice: name => conversation.observe(name) });
  // For the avatar's listener behaviour (nods in your pauses, eye contact): read every frame.
  if (social) Object.assign(social.current, { userSpeaking: listening.state === 'hearing' || microphone.recording,
    level: listening.level || 0, phase: conversation.phase });
  const stop = () => { microphone.cancel(); conversation.stop(); };
  useEffect(() => {
    control.current = { stop };
    return () => { control.current = null; };
  });
  useEffect(() => { onBusy(busy); }, [busy, onBusy]);
  // Face mood: attentive while the person talks, "thinking" while we transcribe/generate.
  const mood = ['transcribing', 'thinking'].includes(conversation.phase) || (conversation.phase === 'generating' && !speaking) ? 'thinking'
    : listening.state === 'hearing' || microphone.recording ? 'listening' : 'idle';
  useEffect(() => { onMood(mood); }, [mood, onMood]);
  useEffect(() => { onHandsFree(handsFree ? listening.state : 'off'); }, [handsFree, listening.state, onHandsFree]);
  useEffect(() => { if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight; }, [conversation.messages]);
  const status = microphone.requesting ? 'WAITING FOR MICROPHONE' : microphone.recording ? 'LISTENING'
    : handsFree && conversation.phase === 'idle' && !speaking ? handsFreeLabels[listening.state] || 'LISTENING' : labels[conversation.phase] || 'LIVE';
  // The status panel lives beside the avatar (outside the hidden drawer) so it is always visible.
  const spokeRef = useRef(false);
  if (conversation.phase === 'idle' || conversation.phase === 'transcribing') spokeRef.current = speech.phase === 'speaking';
  else if (speech.phase === 'speaking') spokeRef.current = true;
  const currentStatus = statusKey({ phase: conversation.phase, kind: conversation.kind, handsFree, handsFreeState: listening.state,
    recording: microphone.recording, speechPhase: speech.phase, spoke: spokeRef.current,
    error: conversation.error || microphone.error || listening.error });
  const lastHeard = [...conversation.messages].reverse().find(m => m.role === 'YOU')?.text || '';
  const lastReply = [...conversation.messages].reverse().find(m => m.role === 'AVATAR' && m.text)?.text || '';
  const statusPanel = avatarId && typeof document !== 'undefined' && createPortal(
    <StatusPanel status={currentStatus} level={listening.level || 0} lastHeard={lastHeard} lastReply={lastReply}
      error={listening.error || conversation.error || microphone.error} female={avatarGender === 'female'}/>, document.body);
  return <section className="conversation-panel" aria-label="Voice conversation">
    {statusPanel}
    <div className="conversation-heading"><h2>VOICE CONVERSATION</h2><span>{online ? 'ONLINE AI' : 'LOCAL AI'}</span></div>
    <p role="status" aria-label="Conversation status">{status}</p>
    {handsFree && <div className="hands-free-meter" aria-hidden="true"><i style={{ width: `${Math.round(listening.level * 100)}%` }}/></div>}
    <div className="conversation-actions">
      <button className={handsFree ? 'hands-free-on' : ''} disabled={!avatarId} aria-pressed={handsFree} onClick={() => {
        speech.unlock();  // this click also allows the avatar's audio to play later
        if (handsFree) { setHandsFree(false); conversation.stop(); }
        else { microphone.cancel(); setHandsFree(true); greet(); }
      }}>{handsFree ? '🎙 HANDS-FREE: ON' : '🎙 HANDS-FREE: OFF'}</button>
      <button disabled={!avatarId || handsFree || (busy && !microphone.recording)} onClick={() => {
        if (microphone.recording) microphone.stop();
        else { conversation.stop(); speech.unlock(); microphone.start(); }
      }}>{microphone.recording ? 'FINISH RECORDING' : '🎤 TALK'}</button>
      <button disabled={!busy && !speaking} onClick={stop}>STOP</button>
      <button disabled={!avatarId || clearing} onClick={async () => {
        microphone.cancel(); setClearing(true);
        try { await conversation.clear(); } finally { setClearing(false); }
      }}>CLEAR</button>
    </div>
    <form className="conversation-input" onSubmit={event => {
      event.preventDefault(); microphone.cancel(); conversation.request(text); setText('');
    }}>
      <input aria-label="Message to local AI" placeholder="Type a message…" maxLength={500} value={text} onChange={e => setText(e.target.value)} disabled={!avatarId || busy}/>
      <button type="submit" disabled={!avatarId || busy || !text.trim()}>SEND</button>
    </form>
    <div className="conversation-transcript" ref={transcript} aria-label="Conversation transcript" aria-live="polite">
      {conversation.messages.map((message, i) => <p key={i}><b>{message.role}</b>{message.text || '…'}</p>)}
    </div>
    {(conversation.error || microphone.error || listening.error) && <p role="alert">{listening.error || conversation.error || microphone.error}</p>}
    <details className="conversation-settings"><summary>Voice conversation settings</summary>
      <label>Microphone<select aria-label="Microphone" value={microphone.device} onChange={e => microphone.setDevice(e.target.value)} disabled={busy}>
        <option value="">System default</option>{microphone.devices.filter(d => d.deviceId && d.deviceId !== 'default').map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Microphone ${i + 1}`}</option>)}
      </select></label>
      <p className="conversation-note">Device names appear after microphone permission is granted.</p>
      <label>Speech recognition<span>Local · CPU</span></label>
      <label>Spoken language<select aria-label="Spoken language" value={conversation.language} onChange={e => conversation.setLanguage(e.target.value)} disabled={busy}>
        <option value="auto">Auto · English / Hindi / Hinglish</option><option value="en">English</option><option value="hi">Hindi / Hinglish</option>
      </select></label>
      <label>AI<span>{online ? 'Online (local if no internet)' : 'Local · CPU'}</span></label>
      <label>Response length<select aria-label="Response length" value={conversation.responseLength} onChange={e => conversation.setResponseLength(e.target.value)} disabled={busy}>
        <option value="short">Short</option><option value="normal">Normal</option>
      </select></label>
      <button disabled={busy} onClick={async () => {
        try {
          const result = await fetch('/avatar/conversation/unload', { method: 'POST' });
          setNotice(result.ok ? 'Local models unloaded. They will load on your next message.' : 'Models are busy. Please retry shortly.');
        } catch { setNotice('Cannot reach the local backend.'); }
      }}>Unload local models</button>
      <button disabled={!avatarId || busy} onClick={async () => {
        try {
          const result = await fetch(`/avatar/${avatarId}/memory/forget`, { method: 'POST' });
          setNotice(result.ok ? 'The avatar forgot your name and saved notes.' : 'Could not clear memory.');
        } catch { setNotice('Cannot reach the local backend.'); }
      }}>Forget my name and notes</button>
      {notice && <p className="conversation-note">{notice}</p>}
    </details>
    {conversation.metrics && <details className="conversation-settings"><summary>Conversation timings</summary>
      <pre data-testid="conversation-metrics" style={{ whiteSpace: 'pre-wrap', fontSize: 10 }}>{JSON.stringify(conversation.metrics, null, 2)}</pre>
    </details>}
    <p className="conversation-note">Turn on HANDS-FREE and just talk: the avatar hears when you start and stop, then replies. Or tap TALK for one message. Audio stays on this computer; recordings are deleted after transcription.</p>
  </section>;
}
