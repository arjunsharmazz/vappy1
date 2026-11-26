import { useEffect, useRef, useState } from 'react';

// Subscribes to the backend camera stream (Server-Sent Events). The renderer reads `target`
// every frame without React re-renders; `status` changes only when camera/presence changes.
export function useGazeTarget(enabled) {
  const target = useRef(null);
  // Full latest camera state (tracking box, face points, feelings) for the live camera panel.
  const latest = useRef(null);
  const [status, setStatus] = useState({ camera: false, present: false, connected: false, available: true });
  useEffect(() => {
    target.current = null;
    if (!enabled || typeof EventSource === 'undefined') {
      setStatus(s => ({ ...s, camera: false, present: false, connected: false }));
      return;
    }
    const source = new EventSource('/vision/stream');
    let last = '';
    source.onmessage = event => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (data.disabled) {  // eye tracking switched off in settings.toml
        target.current = null; source.close();
        setStatus({ camera: false, present: false, connected: false, available: false });
        return;
      }
      latest.current = data.camera ? { ...data, at: performance.now() } : null;
      target.current = data.camera ? { present: !!data.present, x: data.x || 0, y: data.y || 0, at: performance.now() } : null;
      const key = `${data.camera}:${data.present}`;
      if (key !== last) {
        last = key;
        setStatus({ camera: !!data.camera, present: !!data.present, connected: true, available: true, detector: data.detector });
      }
    };
    // EventSource reconnects by itself; meanwhile the avatar simply behaves as without a camera.
    source.onerror = () => { target.current = null; latest.current = null; setStatus(s => ({ ...s, connected: false, camera: false, present: false })); };
    return () => { source.close(); target.current = null; latest.current = null; };
  }, [enabled]);
  return { target, status, latest };
}
