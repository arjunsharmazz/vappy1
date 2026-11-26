import { useCallback, useEffect, useRef, useState } from 'react';

// Recording is opt-in, bounded, and all tracks are released on every exit path.
export function useMicrophone(onAudio) {
  const [recording, setRecording] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState('');
  const [devices, setDevices] = useState([]);
  const [device, setDevice] = useState('');
  const active = useRef(null), generation = useRef(0), callback = useRef(onAudio);
  callback.current = onAudio;
  const cancel = useCallback(() => {
    generation.current++;
    const r = active.current; active.current = null;
    if (r) {
      clearTimeout(r.timer);
      r.recorder.onstop = null;
      if (r.recorder.state !== 'inactive') r.recorder.stop();
      r.stream.getTracks().forEach(t => t.stop());
    }
    setRecording(false); setRequesting(false);
  }, []);
  useEffect(() => cancel, [cancel]);
  const stop = useCallback(() => {
    const r = active.current;
    if (r?.recorder.state === 'recording') r.recorder.stop();
  }, []);
  const start = useCallback(async () => {
    cancel(); setError(''); setRequesting(true);
    const token = generation.current;
    let stream;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error();
      stream = await navigator.mediaDevices.getUserMedia({ audio: {
        ...(device ? { deviceId: { exact: device } } : {}), echoCancellation: true, noiseSuppression: true,
      }});
      if (token !== generation.current) { stream.getTracks().forEach(t => t.stop()); return; }
      const list = await navigator.mediaDevices.enumerateDevices();
      if (token !== generation.current) { stream.getTracks().forEach(t => t.stop()); return; }
      setDevices(list.filter(d => d.kind === 'audioinput'));
      const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported(t));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const parts = []; let bytes = 0;
      const r = { recorder, stream, started: performance.now() }; active.current = r;
      recorder.ondataavailable = event => {
        bytes += event.data.size;
        if (bytes > 8 * 1024 * 1024) { cancel(); setError('Recording is too large. Please try a shorter message.'); }
        else if (event.data.size) parts.push(event.data);
      };
      recorder.onerror = () => { cancel(); setError('Microphone unavailable.'); };
      recorder.onstop = () => {
        clearTimeout(r.timer); stream.getTracks().forEach(t => t.stop()); active.current = null;
        setRecording(false);
        if (token === generation.current) callback.current(new Blob(parts, { type: recorder.mimeType }), (performance.now() - r.started) / 1000);
      };
      recorder.start(250); setRecording(true); setRequesting(false);
      r.timer = setTimeout(stop, 30000);
    } catch {
      stream?.getTracks().forEach(t => t.stop());
      if (token === generation.current) { cancel(); setError('Microphone unavailable.'); }
    }
  }, [cancel, device, stop]);
  return { start, stop, cancel, recording, requesting, error, devices, device, setDevice };
}
