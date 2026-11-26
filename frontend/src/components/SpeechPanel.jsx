import { forwardRef, useImperativeHandle, useRef, useState } from 'react';

const SpeechPanel = forwardRef(function SpeechPanel({ enabled, speech, avatarId, animationState }, ref) {
  const [text, setText] = useState('Hello! I am your AI Living Frame. Now I can talk.');
  const textarea = useRef(null);
  const busy = speech.phase === 'generating' || speech.phase === 'speaking';
  useImperativeHandle(ref, () => ({
    focus: () => { textarea.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }); textarea.current?.focus(); },
  }), []);
  return <section className="speech-panel" aria-labelledby="speech-title">
    <div className="speech-heading"><h2 id="speech-title">MAKE YOUR AVATAR SPEAK</h2><span>OFFLINE VOICE</span></div>
    <label className="sr-only" htmlFor="speech-text">Text for your avatar to say</label>
    <textarea id="speech-text" ref={textarea} maxLength={500} value={text} onChange={event => setText(event.target.value)}
      placeholder="Type something for your avatar to say..." disabled={busy} rows={3}/>
    <div className="speech-actions">
      <span className="character-count" aria-live="polite">{text.length} / 500</span>
      {busy ? <button className="stop-button" onClick={speech.stop}>■ STOP</button> :
        <button className="upload-button" disabled={!enabled || !text.trim()} onClick={() => speech.speak(text)}>SPEAK</button>}
    </div>
    <p className="speech-feedback" role="status" aria-label="Speech status">
      {speech.phase === 'generating' ? 'GENERATING VOICE...' : speech.phase === 'speaking' ? '● SPEAKING' : enabled ? 'Ready when you are. Sound plays through your browser.' : 'Upload a portrait with clear eyes and mouth to enable speech.'}
    </p>
    {speech.error && <p className="animation-warning" role="alert">{speech.error}</p>}
    <details className="speech-debug">
      <summary>Speech diagnostics</summary>
      <dl><dt>Avatar ID</dt><dd>{avatarId || '—'}</dd>
        <dt>TTS</dt><dd data-testid="tts-status">{speech.debug.tts}</dd>
        <dt>Audio</dt><dd data-testid="audio-status">{speech.debug.audio}</dd>
        <dt>Animation</dt><dd>{animationState}</dd>
        <dt>Audio amplitude</dt><dd data-testid="audio-amplitude">{speech.debug.amplitude.toFixed(4)}</dd>
      </dl>
    </details>
  </section>;
});
export default SpeechPanel;
