export default function AvatarStatus({ status, message, avatar, state, live, warning, speechPhase, onStop }) {
  const label = speechPhase === 'generating' ? '◌ GENERATING VOICE' : speechPhase === 'speaking' ? '● SPEAKING' : live ? '● LIVE' : '● STILL';
  return <>
    <div className={`status status-${status}`} role="status" aria-label="Avatar status" aria-live="polite"><i/>{message}</div>
    {avatar?.face_detected && <div className="live-line"><span className={live || speechPhase === 'speaking' ? 'live-dot' : ''} data-testid="live-status">{label}</span><span data-testid="animation-state">{state.replaceAll('_', ' ')}</span>{speechPhase === 'speaking' && <button className="frame-stop" onClick={onStop} aria-label="Stop speech">STOP</button>}</div>}
    {warning && <p className="animation-warning" role="alert">{warning}</p>}
    {avatar && <p className="avatar-id" title={avatar.avatar_id}>AVATAR / {avatar.avatar_id}</p>}
  </>;
}
