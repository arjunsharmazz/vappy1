import { useEffect, useRef, useState } from 'react';
import '../camera.css';

// Live camera panel (left side): the backend's camera as MJPEG, with a green tracking box that
// follows the face at camera speed, the face outline/mesh, hands, head direction and a running
// log of the feelings and gestures the avatar reads. Drawn on a canvas every animation frame
// from a ref, so the 15-30 Hz overlay never re-renders React; the text HUD updates at ~4 Hz.
const HAND_LINKS = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
const GREEN = '#2bff88', CYAN = 'rgba(80, 220, 255, .85)', AMBER = '#ffc53d';
const lerp = (a, b, t) => a + (b - a) * t;
const pct = value => `${Math.round((value || 0) * 100)}%`;
const EN = { neutral: 'NEUTRAL', smiling: 'SMILING', laughing: 'LAUGHING', laughing_hard: 'LAUGHING HARD', surprised: 'SURPRISED',
  sad: 'SAD', crying: 'CRYING', angry: 'ANGRY', disgusted: 'DISGUST', fearful: 'FEAR', tense: 'TENSE', thinking: 'THINKING',
  tired: 'TIRED', yawning: 'YAWNING', confused: 'CONFUSED' };

export default function CameraPanel({ latest, mirror = true, status, onClose, waiting = null, onEnable = () => {} }) {
  const canvas = useRef(null);
  const view = useRef(null);
  const [hud, setHud] = useState(null);
  const [videoError, setVideoError] = useState(false);
  const [videoKey, setVideoKey] = useState(0);
  const log = useRef([]);
  const [logLines, setLogLines] = useState([]);

  // A broken MJPEG connection (backend restart) retries by itself.
  useEffect(() => {
    if (!videoError) return;
    const timer = setTimeout(() => { setVideoError(false); setVideoKey(k => k + 1); }, 2500);
    return () => clearTimeout(timer);
  }, [videoError]);

  useEffect(() => {
    let frame, smooth = null, scan = 0, lastPresent = null;
    const push = line => {
      const time = new Date().toLocaleTimeString('en-GB');
      log.current = [...log.current.slice(-30), { time, ...line }];
    };
    const draw = () => {
      frame = requestAnimationFrame(draw);
      const el = canvas.current, box = view.current;
      if (!el || !box) return;
      const w = box.clientWidth, h = box.clientHeight, dpr = window.devicePixelRatio || 1;
      if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) { el.width = Math.round(w * dpr); el.height = Math.round(h * dpr); }
      const ctx = el.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const data = latest.current;
      const X = x => (mirror ? 1 - x : x) * w, Y = y => y * h;
      // Frame furniture: crosshair, corner ticks.
      ctx.strokeStyle = 'rgba(43, 255, 136, .18)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(w / 2 - 10, h / 2); ctx.lineTo(w / 2 + 10, h / 2); ctx.moveTo(w / 2, h / 2 - 10); ctx.lineTo(w / 2, h / 2 + 10); ctx.stroke();
      const present = !!data?.present;
      if (lastPresent !== null && present !== lastPresent) push(present ? { kind: 'lock', text: 'TARGET LOCKED · face acquired' } : { kind: 'lost', text: 'TARGET LOST · nobody in front' });
      lastPresent = present;
      if (!data?.box) { smooth = null; return; }
      // Smooth box (camera ~15 Hz → display 60 Hz).
      const [bx0, by0, bx1, by1] = data.box;
      const target = [Math.min(X(bx0), X(bx1)), Y(by0), Math.max(X(bx0), X(bx1)), Y(by1)];
      smooth = smooth ? smooth.map((v, i) => lerp(v, target[i], .35)) : target;
      const [x0, y0, x1, y1] = smooth, bw = x1 - x0, bh = y1 - y0;
      const analysis = data.analysis;
      // Face points arrive ~4x/s: shift them with the fast box so they stay on the face.
      let dx = 0, dy = 0;
      if (analysis?.face_box) {
        const [ax0, ay0, ax1, ay1] = analysis.face_box;
        dx = (bx0 + bx1) / 2 - (ax0 + ax1) / 2; dy = (by0 + by1) / 2 - (ay0 + ay1) / 2;
      }
      const PX = p => X(p[0] + dx), PY = p => Y(p[1] + dy);
      if (analysis?.mesh) {
        ctx.fillStyle = 'rgba(80, 220, 255, .45)';
        for (const p of analysis.mesh) ctx.fillRect(PX(p) - 1, PY(p) - 1, 2, 2);
      }
      if (analysis?.contours) {
        ctx.strokeStyle = CYAN; ctx.lineWidth = 1.2;
        for (const [name, points] of Object.entries(analysis.contours)) {
          if (name === 'irises') continue;
          ctx.beginPath();
          points.forEach((p, i) => (i ? ctx.lineTo(PX(p), PY(p)) : ctx.moveTo(PX(p), PY(p))));
          ctx.stroke();
        }
        for (const p of analysis.contours.irises || []) {
          ctx.strokeStyle = GREEN; ctx.beginPath(); ctx.arc(PX(p), PY(p), 3, 0, Math.PI * 2); ctx.stroke();
        }
        // Head direction arrow from the nose tip.
        const nose = analysis.contours.nose?.[6];
        if (nose && analysis.head) {
          const [yaw, pitch] = analysis.head, len = bw * .55;
          const ex = PX(nose) + Math.sin(yaw * Math.PI / 180) * len * (mirror ? -1 : 1);
          const ey = PY(nose) - Math.sin(pitch * Math.PI / 180) * len;
          ctx.strokeStyle = AMBER; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(PX(nose), PY(nose)); ctx.lineTo(ex, ey); ctx.stroke();
          ctx.beginPath(); ctx.arc(ex, ey, 3, 0, Math.PI * 2); ctx.fillStyle = AMBER; ctx.fill();
        }
      }
      (analysis?.hands || []).forEach((hand, index) => {
        const n = analysis.fingers?.per_hand?.[index];
        if (n != null) {  // finger count next to each hand
          ctx.font = '700 15px ui-monospace, Consolas, monospace';
          const tag = `✋ ${n}`, tx = X(hand[0][0]) - 18, ty = Y(hand[0][1]) + 22;
          ctx.fillStyle = 'rgba(30, 20, 0, .8)'; ctx.fillRect(tx - 4, ty - 15, ctx.measureText(tag).width + 8, 20);
          ctx.fillStyle = AMBER; ctx.fillText(tag, tx, ty);
        }
      });
      for (const hand of analysis?.hands || []) {
        ctx.strokeStyle = AMBER; ctx.lineWidth = 1.6;
        ctx.beginPath();
        for (const [a, b] of HAND_LINKS) { ctx.moveTo(X(hand[a][0]), Y(hand[a][1])); ctx.lineTo(X(hand[b][0]), Y(hand[b][1])); }
        ctx.stroke();
        ctx.fillStyle = '#fff';
        for (const p of hand) ctx.fillRect(X(p[0]) - 1.5, Y(p[1]) - 1.5, 3, 3);
      }
      // Tracking box: thin frame, bright corner brackets, moving scan line.
      ctx.strokeStyle = 'rgba(43, 255, 136, .45)'; ctx.lineWidth = 1; ctx.strokeRect(x0, y0, bw, bh);
      const c = Math.min(bw, bh) * .22;
      ctx.strokeStyle = GREEN; ctx.lineWidth = 3; ctx.shadowColor = GREEN; ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.moveTo(x0, y0 + c); ctx.lineTo(x0, y0); ctx.lineTo(x0 + c, y0);
      ctx.moveTo(x1 - c, y0); ctx.lineTo(x1, y0); ctx.lineTo(x1, y0 + c);
      ctx.moveTo(x1, y1 - c); ctx.lineTo(x1, y1); ctx.lineTo(x1 - c, y1);
      ctx.moveTo(x0 + c, y1); ctx.lineTo(x0, y1); ctx.lineTo(x0, y1 - c);
      ctx.stroke(); ctx.shadowBlur = 0;
      scan = (scan + .012) % 1;
      const sy = y0 + bh * scan;
      const gradient = ctx.createLinearGradient(0, sy - 10, 0, sy);
      gradient.addColorStop(0, 'rgba(43,255,136,0)'); gradient.addColorStop(1, 'rgba(43,255,136,.35)');
      ctx.fillStyle = gradient; ctx.fillRect(x0, sy - 10, bw, 10);
      // Labels: tracking confidence above, feeling below.
      ctx.font = '600 11px ui-monospace, Consolas, monospace';
      const top = `TRACKING ${pct(data.score)}`;
      ctx.fillStyle = GREEN; ctx.fillRect(x0, y0 - 17, ctx.measureText(top).width + 10, 16);
      ctx.fillStyle = '#04140b'; ctx.fillText(top, x0 + 5, y0 - 5);
      if (analysis?.emotion) {
        ctx.font = '600 13px "Noto Sans Devanagari", "Nirmala UI", system-ui, sans-serif';
        const label = `${analysis.emotion_hi} · ${pct(analysis.confidence)}`;
        const lw = ctx.measureText(label).width + 12;
        ctx.fillStyle = 'rgba(4, 20, 11, .85)'; ctx.fillRect(x0, y1 + 3, lw, 20);
        ctx.strokeStyle = GREEN; ctx.lineWidth = 1; ctx.strokeRect(x0, y1 + 3, lw, 20);
        ctx.fillStyle = GREEN; ctx.fillText(label, x0 + 6, y1 + 18);
      }
    };
    frame = requestAnimationFrame(draw);
    // Text HUD + event log at ~4 Hz.
    let seenEvents = new Set();
    const timer = setInterval(() => {
      const data = latest.current;
      for (const e of data?.analysis?.events || []) {
        const key = `${e.time}|${e.name}`;
        if (seenEvents.has(key)) continue;
        seenEvents.add(key);
        log.current = [...log.current.slice(-30), { time: e.time, kind: 'event', text: `${(EN[e.name] || e.name.toUpperCase().replace(/_/g, ' '))} · ${e.label}${e.score < 1 ? ` (${pct(e.score)})` : ''}` }];
      }
      if (seenEvents.size > 200) seenEvents = new Set([...seenEvents].slice(-60));
      setHud(data ? { fps: data.fps, res: data.resolution, present: data.present, score: data.score, detector: data.detector, analysis: data.analysis } : null);
      setLogLines(log.current.slice(-9));
    }, 250);
    return () => { cancelAnimationFrame(frame); clearInterval(timer); };
  }, [latest, mirror]);

  const a = hud?.analysis;
  const live = !waiting && status.connected && status.camera;
  return <aside className="cam-panel" aria-label="Live camera tracking">
    <div className="cam-head">
      <span className={`cam-dot ${live ? 'on' : ''}`}/>
      <b>{live ? 'LIVE' : 'OFFLINE'}</b><span>VISION · TRACKING</span>
      <button onClick={onClose} aria-label="Hide camera panel">✕</button>
    </div>
    <div className="cam-view" ref={view}>
      {waiting
        ? <div className="cam-wait"><p>{waiting.text}</p>{waiting.action && <button className="cam-enable" onClick={onEnable}>{waiting.action}</button>}</div>
        : live && !videoError
        ? <img key={videoKey} src={`/vision/video?k=${videoKey}`} alt="Live camera" style={{ transform: mirror ? 'scaleX(-1)' : 'none' }} onError={() => setVideoError(true)}/>
        : <div className="cam-wait">{status.available === false ? 'Camera off in settings' : 'Connecting to camera…'}</div>}
      <canvas ref={canvas}/>
      <div className="cam-corner tl">REC ● {hud?.res ? `${hud.res[0]}×${hud.res[1]}` : ''}</div>
      <div className="cam-corner tr">{hud?.fps ? `${hud.fps.toFixed(1)} FPS` : ''}</div>
    </div>
    <div className="cam-hud">
      <div className="cam-feeling">
        <small>FEELING</small>
        <strong>{a ? a.emotion_hi : hud?.present ? 'पढ़ रहे हैं…' : 'कोई सामने नहीं'}</strong>
        <span>{a ? `${EN[a.emotion] || a.emotion} · ${pct(a.confidence)} · ${a.emotion_seconds.toFixed(0)}s` : '—'}</span>
      </div>
      {a && <div className="cam-bars">{Object.entries(a.scores).map(([name, value]) =>
        <div key={name} className={name === a.emotion ? 'top' : ''}><label>{EN[name] || name}</label><i style={{ width: pct(value) }}/><em>{pct(value)}</em></div>)}
      </div>}
      {a?.gestures_hi?.length > 0 && <div className="cam-chips">{a.gestures_hi.map(g => <span key={g}>{g}</span>)}</div>}
      <div className="cam-grid">
        <div><small>YAW</small><b>{a?.head ? `${a.head[0] > 0 ? '+' : ''}${a.head[0].toFixed(0)}°` : '—'}</b></div>
        <div><small>PITCH</small><b>{a?.head ? `${a.head[1] > 0 ? '+' : ''}${a.head[1].toFixed(0)}°` : '—'}</b></div>
        <div><small>ROLL</small><b>{a?.head ? `${a.head[2] > 0 ? '+' : ''}${a.head[2].toFixed(0)}°` : '—'}</b></div>
        <div><small>FACE</small><b>{hud?.present ? pct(hud.score) : '—'}</b></div>
        <div><small>AI FPS</small><b>{a?.fps ? a.fps.toFixed(1) : '—'}</b></div>
        <div><small>FINGERS</small><b>{a?.fingers ? (a.fingers.shown ?? a.fingers.total) : '—'}</b></div>
        <div><small>MODEL MS</small><b>{a?.timings ? Math.round((a.timings.face_ms || 0) + (a.timings.hands_ms || 0) / 2 + (a.timings.emotion_ms || 0) / 3) : '—'}</b></div>
      </div>
      <div className="cam-log" aria-label="Vision event log">
        {logLines.length ? logLines.map((line, i) => <p key={i} className={line.kind}><time>[{line.time}]</time> {line.text}</p>)
          : <p className="dim">&gt; waiting for events…</p>}
      </div>
      <p className="cam-note">Video stays on this computer · nothing is saved</p>
    </div>
  </aside>;
}
