import { useEffect, useRef, useState } from 'react';
import '../status.css';

// Always-visible status beside the avatar: what is happening right now (big emoji + words), a live
// timer that turns yellow/red when a step is slow, the microphone level while you talk, and a
// timeline of the last turn, so you can see where time goes.
const STEPS = {
  idle:      { emoji: '😊', label: 'तैयार हूँ', hint: 'HANDS-FREE चालू करें या TALK दबाएँ' },
  ready:     { emoji: '👂', label: 'सुन रहा हूँ — बोलिए', hint: 'Listening · just speak' },
  hearing:   { emoji: '🎙️', label: 'आप बोल रहे हैं…', hint: 'Recording your voice', slow: [15, 25] },
  transcribing: { emoji: '📝', label: 'आपकी बात समझ रहा हूँ', hint: 'Voice → text', slow: [4, 8] },
  thinking:  { emoji: '🤔', label: 'सोच रहा हूँ…', hint: 'Thinking of a reply', slow: [5, 10] },
  voice:     { emoji: '🔊', label: 'आवाज़ तैयार कर रहा हूँ', hint: 'Preparing the voice', slow: [3, 6] },
  speaking:  { emoji: '🗣️', label: 'बोल रहा हूँ', hint: 'Speaking' },
  noticing:  { emoji: '👀', label: 'आपको देखकर ख़ुद बोल रहा है', hint: 'Not something you said — the avatar noticed you', slow: [6, 12] },
  greeting:  { emoji: '👋', label: 'नमस्ते कह रहा है', hint: 'Greeting you' },
  paused:    { emoji: '⏸️', label: 'रुका हुआ — कोई सामने नहीं', hint: 'Paused: nobody in front' },
  error:     { emoji: '⚠️', label: 'कुछ गड़बड़ हुई', hint: '' },
};
const SHORT = { hearing: '🎙', transcribing: '📝', thinking: '🤔', voice: '🔊', speaking: '🗣', noticing: '👀', greeting: '👋' };

export function statusKey({ phase, kind, handsFree, handsFreeState, recording, speechPhase, spoke, error }) {
  // Activity always wins; an error (e.g. no microphone) shows only while nothing else happens.
  if (recording || handsFreeState === 'hearing') return 'hearing';
  if (phase === 'transcribing') return 'transcribing';
  if (phase !== 'idle' || speechPhase === 'speaking' || speechPhase === 'generating') {
    if (kind === 'greeting') return 'greeting';
    if (speechPhase === 'speaking' || spoke) return kind === 'observation' ? 'noticing' : 'speaking';
    if (kind === 'observation') return 'noticing';
    return phase === 'generating' || speechPhase === 'generating' ? 'voice' : 'thinking';
  }
  if (error) return 'error';
  if (handsFree) return handsFreeState === 'paused' ? 'paused' : 'ready';
  return 'idle';
}

export default function StatusPanel({ status, level = 0, lastHeard = '', lastReply = '', error = '', female = false }) {
  const [now, setNow] = useState(performance.now());
  const since = useRef({ key: status, at: performance.now() });
  const turn = useRef([]);           // steps of the turn in progress
  const [last, setLast] = useState([]);  // the last finished turn
  useEffect(() => {
    const ended = since.current, at = performance.now();
    if (ended.key === status) return;
    if (SHORT[ended.key]) turn.current.push({ key: ended.key, seconds: (at - ended.at) / 1000 });
    // A turn ends when the avatar is back to waiting.
    if (['ready', 'idle', 'paused'].includes(status) && turn.current.length) { setLast(turn.current); turn.current = []; }
    since.current = { key: status, at };
    setNow(at);
  }, [status]);
  useEffect(() => {
    const timer = setInterval(() => setNow(performance.now()), 200);
    return () => clearInterval(timer);
  }, []);
  const step = STEPS[status] || STEPS.idle;
  const elapsed = Math.max(0, (now - since.current.at) / 1000);
  const timed = !!step.slow || status === 'speaking';
  const tone = step.slow ? (elapsed >= step.slow[1] ? 'late' : elapsed >= step.slow[0] ? 'slow' : 'ok') : 'ok';
  const showLevel = status === 'ready' || status === 'hearing';
  return <aside className={`status-panel s-${status}`} aria-label="What the avatar is doing" aria-live="polite">
    <div className="status-emoji" aria-hidden="true">{step.emoji}</div>
    <div className="status-label">{female ? step.label.replace(/रहा/g, 'रही') : step.label}</div>
    <div className="status-hint">{status === 'error' ? error : step.hint}</div>
    {timed && <div className={`status-timer ${tone}`}>{elapsed.toFixed(1)}s{tone === 'slow' ? ' · थोड़ा धीमा' : tone === 'late' ? ' · बहुत धीमा (internet?)' : ''}</div>}
    {showLevel && <div className="status-level" aria-hidden="true">
      {Array.from({ length: 12 }, (_, i) => <i key={i} className={level * 12 > i ? 'on' : ''}/>)}
    </div>}
    <div className="status-flow" aria-label="Steps">
      {['hearing', 'transcribing', 'thinking', 'voice', 'speaking'].map(key =>
        <span key={key} className={key === status || (key === 'speaking' && status === 'noticing') ? 'now' : ''}>{SHORT[key]}</span>)}
    </div>
    {last.length > 0 && <div className="status-last">
      <small>पिछली बार · last turn</small>
      <p>{last.map((s, i) => <span key={i} className={STEPS[s.key]?.slow && s.seconds >= STEPS[s.key].slow[0] ? 'slowstep' : ''}>
        {SHORT[s.key]} {s.seconds.toFixed(1)}s</span>)}</p>
    </div>}
    {lastHeard && <div className="status-said"><small>आपने कहा</small><p>“{lastHeard}”</p></div>}
    {lastReply && <div className="status-said reply"><small>जवाब</small><p>{lastReply}</p></div>}
  </aside>;
}
