import { useEffect, useRef, useState } from 'react';

export default function NeuralControls({ avatarId, busy, mode, setMode, onClip }) {
  const [quality, setQuality] = useState('fast');
  const [action, setAction] = useState('SMILE');
  const [status, setStatus] = useState('');
  const [pending, setPending] = useState(false);
  const run = useRef(null);
  const stop = () => {
    const job = run.current; run.current = null;
    if (job) {
      job.abort.abort();
      if (job.id) fetch(`/avatar/${avatarId}/neural/jobs/${job.id}/cancel`, { method: 'POST' }).catch(() => {});
    }
    setPending(false);
  };
  useEffect(() => () => { stop(); }, [avatarId]);
  useEffect(() => { if (busy || mode !== 'neural') { stop(); onClip(null); } }, [busy, mode]);
  const generate = async () => {
    stop(); onClip(null); setPending(true); setStatus('Preparing local neural preview…');
    const job = { abort: new AbortController() }; run.current = job;
    try {
      const result = await fetch(`/avatar/${avatarId}/neural/jobs`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, quality, duration: 1 }),
      });
      let data = await result.json();
      if (!result.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Neural preview unavailable.');
      job.id = data.job_id;
      // If Stop happened before the job ID arrived, cancel the now-known job too.
      if (run.current !== job) {
        fetch(`/avatar/${avatarId}/neural/jobs/${job.id}/cancel`, { method: 'POST' }).catch(() => {}); return;
      }
      let lastProgress = performance.now();
      let progressMarker = '';
      while (!['READY', 'ERROR', 'CANCELLED'].includes(data.state)) {
        const marker = `${data.state}:${data.progress || 0}`;
        if (marker !== progressMarker) { progressMarker = marker; lastProgress = performance.now(); }
        if (performance.now() - lastProgress > 180000) throw new Error('Neural preview stopped making progress. Please try Fast quality.');
        setStatus(`${data.state} · ${Math.round((data.progress || 0) * 100)}%`);
        await new Promise(resolve => setTimeout(resolve, 700));
        if (run.current !== job) return;
        const response = await fetch(`/avatar/${avatarId}/neural/jobs/${job.id}`, { signal: job.abort.signal });
        if (!response.ok) throw new Error('Neural preview unavailable.');
        data = await response.json();
      }
      if (run.current !== job) return;
      if (data.state !== 'READY') throw new Error('Neural preview failed. Lightweight animation is active.');
      if (!data.video_url?.startsWith(`/avatar/${avatarId}/neural/cache/`)) throw new Error('Invalid local preview.');
      onClip(data.video_url);
      setStatus(data.cached ? 'Cached neural preview ready.' : `Neural preview ready · ${data.generation_seconds.toFixed(1)} seconds to render.`);
    } catch (error) {
      if (run.current === job) { setStatus(error.message); onClip(null); stop(); }
    } finally { if (run.current === job) { run.current = null; setPending(false); } }
  };
  return <section className="conversation-panel" aria-label="Animation settings" style={{ marginTop: 16 }}>
    <div className="conversation-heading"><h2>ANIMATION</h2><span>LOCAL</span></div>
    <div className="conversation-settings">
      <label>Animation<select aria-label="Animation mode" value={mode} onChange={e => setMode(e.target.value)}>
        <option value="neural-live">Prepared neural face</option><option value="lightweight">Lightweight (approximate)</option><option value="neural">Neural video previews</option>
      </select></label>
      {mode === 'neural' && <>
        <label>Neural quality<select aria-label="Neural quality" value={quality} onChange={e => setQuality(e.target.value)} disabled={pending}>
          <option value="fast">Fast · 128px / 4 fps</option><option value="balanced">Balanced · 256px / 8 fps</option><option value="quality">Quality · 256px / 12 fps</option>
        </select></label>
        <label>Preview expression<select aria-label="Neural expression" value={action} onChange={e => setAction(e.target.value)} disabled={pending}>
          <option value="SMILE">Smile</option><option value="BLINK">Blink</option><option value="LOOK_LEFT">Look left</option><option value="LOOK_RIGHT">Look right</option><option value="IDLE">Idle</option>
        </select></label>
        <div className="conversation-actions"><button disabled={!avatarId || busy || pending} onClick={generate}>GENERATE NEURAL PREVIEW</button>
          {pending && <button onClick={() => { stop(); setStatus('Cancelled. Lightweight animation is active.'); }}>CANCEL PREVIEW</button>}</div>
        <p className="conversation-note">Neural previews render locally before playback. Live conversation uses Lightweight animation to keep speech responsive.</p>
        {status && <p role="status" aria-label="Neural status">{status}</p>}
      </>}
    </div>
  </section>;
}
