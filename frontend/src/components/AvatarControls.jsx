export default function AvatarControls({ enabled, onAction, automatic, onToggle, state, onSpeak }) {
  return <>
    <div className="controls flex w-full max-w-lg justify-center gap-3">
      <button className="control" disabled={!enabled} onClick={() => onAction('SMILE')}>☺ <span className="control-name">Smile</span></button>
      <button className="control" disabled={!enabled} onClick={() => onAction('LAUGH')}>☻ <span className="control-name">Laugh</span></button>
      <button className="control" disabled={!enabled} onClick={onSpeak} aria-label="Edit speech text">♩ <span className="control-name">Speak</span></button>
    </div>
    <div className="small-controls" aria-label="Additional animation controls">
      <button disabled={!enabled} onClick={() => onAction('LOOK_LEFT')}>← Look Left</button>
      <button disabled={!enabled} onClick={() => onAction('BLINK')}>Blink</button>
      <button disabled={!enabled} onClick={() => onAction('BROWS')}>Eyebrows</button>
      <button disabled={!enabled} onClick={() => onAction('LOOK_RIGHT')}>Look Right →</button>
      <button disabled={!enabled} onClick={onToggle} aria-pressed={!automatic}>{automatic ? 'Pause idle' : 'Resume idle'}</button>
    </div>
    <p className="phase-note">Local expressions · Your words, spoken offline</p>
    <span className="sr-only" role="status" aria-label="Animation state">{state}</span>
  </>;
}
