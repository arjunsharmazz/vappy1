import { textToVisemes, fitVisemeTimeline, timelineFromWords } from '../animation/visemeTimeline';
import { useCallback, useEffect, useRef, useState } from 'react';

const emptyMotion = () => ({ speaking: false, mouthOpen: 0, amplitude: 0 });
export const amplitudeToMouth = rms => {
  if (rms < .008) return 0;
  if (rms < .04) return .15 + (rms - .008) / .032 * .15;
  if (rms < .12) return .30 + (rms - .04) / .08 * .25;
  return Math.min(.75, .55 + (rms - .12) / .18 * .20);
};

// One request/audio graph per utterance. React receives debug values at 10 Hz, not audio rate.
export function useAvatarSpeech(avatarId) {
  const [phase, setPhase] = useState('idle');
  const [error, setError] = useState('');
  const [debug, setDebug] = useState({ tts: 'READY', audio: 'READY', amplitude: 0 });
  const motion = useRef(emptyMotion());
  const resources = useRef(null);
  const sequence = useRef(0);
  const mounted = useRef(true);
  const primed = useRef(null);
  const unlock = useCallback(() => {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return;
    if (!primed.current || primed.current.state === 'closed') primed.current = new Context();
    primed.current.resume().catch(() => {});
  }, []);

  const cleanup = useCallback(() => {
    sequence.current++;
    const session = resources.current;
    resources.current = null;
    motion.current = emptyMotion();
    if (!session) return;
    session.finish?.({ ok: false, cancelled: true });
    clearTimeout(session.timeout);
    session.abort.abort();
    cancelAnimationFrame(session.frame);
    if (session.source) {
      session.source.onended = null;
      try { session.source.stop(); } catch { /* Already stopped. */ }
      session.source.disconnect();
    }
    session.analyser?.disconnect();
    session.context.onstatechange = null;
    if (session.context.state !== 'closed') session.context.close().catch(() => {});
  }, []);

  const stop = useCallback(() => {
    cleanup();
    if (primed.current) { primed.current.close().catch(() => {}); primed.current = null; }
    if (mounted.current) {
      setPhase('idle');
      setDebug(value => ({ ...value, audio: 'READY', amplitude: 0 }));
    }
  }, [cleanup]);

  useEffect(() => {
    mounted.current = true;
    setPhase('idle'); setError('');
    setDebug({ tts: 'READY', audio: 'READY', amplitude: 0 });
    return () => {
      mounted.current = false; cleanup();
      if (primed.current) { primed.current.close().catch(() => {}); primed.current = null; }
    };
  }, [avatarId, cleanup]);

  // Synthesize ahead of time: the next sentence is generated and downloaded while the current
  // one plays, so sentences follow each other without a gap. Resolves to { result, data } or
  // rejects; never touches the playing audio.
  const prepare = useCallback((text, signal) => {
    const value = text.trim();
    return (async () => {
      const requestedAt = performance.now();
      const response = await fetch('/avatar/' + avatarId + '/speak', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: value }), signal,
      });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.success) {
        const detail = typeof result?.detail === 'string' ? result.detail : Array.isArray(result?.detail) ? result.detail[0]?.msg : null;
        throw new Error(detail || 'Could not generate voice. Check that the local backend is running.');
      }
      if (!result.audio_url?.startsWith('/avatar/' + avatarId + '/audio/')) throw new Error('Invalid local audio URL.');
      const wav = await fetch(result.audio_url, { signal });
      if (!wav.ok) throw new Error('The generated audio could not be loaded. Please try Speak again.');
      return { result, data: await wav.arrayBuffer(), ttsSeconds: (performance.now() - requestedAt) / 1000 };
    })();
  }, [avatarId]);

  const speak = useCallback(async (text, options = {}) => {
    const value = text.trim();
    if (!avatarId || !value || text.length > 500 || !/[\p{L}\p{N}]/u.test(value)) {
      setError('Enter 1–500 characters containing words or numbers.');
      return { ok: false, error: 'Enter 1–500 characters containing words or numbers.' };
    }
    const visemeParts = textToVisemes(value);
    cleanup();
    const token = sequence.current;
    setError(''); setPhase('generating');
    setDebug({ tts: 'GENERATING', audio: 'READY', amplitude: 0 });
    let stage = 'tts';
    const requestedAt = performance.now();
    try {
      const Context = window.AudioContext || window.webkitAudioContext;
      if (!Context) throw new Error('This browser does not support local audio playback. Try Chrome or Edge.');
      // Resume during the click, before the asynchronous synthesis request.
      const context = primed.current || new Context();
      primed.current = null;
      const abort = new AbortController();
      const session = { context, abort, frame: null, source: null, analyser: null };
      resources.current = session;
      session.timeout = setTimeout(() => abort.abort(), 100000);
      await context.resume();
      if (token !== sequence.current) return;
      // Only this avatar's WAV endpoint is accepted (checked in prepare).
      const ready = await (options.prepared || prepare(value, abort.signal));
      const ttsSeconds = options.prepared ? ready.ttsSeconds : (performance.now() - requestedAt) / 1000;
      if (token !== sequence.current) return;
      stage = 'audio';
      setDebug({ tts: 'READY', audio: 'LOADING', amplitude: 0 });
      const buffer = await context.decodeAudioData(ready.data.slice(0));
      if (token !== sequence.current) return;
      if (buffer.duration < .05) throw new Error('The generated audio is empty.');
      // Real word timings from the voice when available; otherwise an estimate from text + audio.
      const timeline = (ready.result?.words?.length && timelineFromWords(ready.result.words, buffer.duration))
        || fitVisemeTimeline(visemeParts, buffer.duration, buffer);
      clearTimeout(session.timeout);
      await context.resume();
      if (token !== sequence.current) return;
      if (context.state !== 'running') throw new Error('Audio playback is blocked. Click Speak again to enable sound.');
      const source = context.createBufferSource();
      const analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = .65;
      source.buffer = buffer;
      source.connect(analyser);
      analyser.connect(context.destination);
      session.source = source; session.analyser = analyser;
      let playbackStarted = 0;
      const samples = new Float32Array(analyser.fftSize);
      let smoothMouth = 0, lastDebug = 0, lastTime = performance.now();
      const analyse = now => {
        if (resources.current !== session) return;
        analyser.getFloatTimeDomainData(samples);
        let power = 0;
        for (const sample of samples) power += sample * sample;
        const amplitude = Math.sqrt(power / samples.length);
        const target = amplitudeToMouth(amplitude);
        const elapsed = Math.min(100, Math.max(1, now - lastTime));
        lastTime = now;
        const blend = 1 - Math.exp(-elapsed / (target > smoothMouth ? 45 : 70));
        smoothMouth += (target - smoothMouth) * blend;
        if (target === 0 && smoothMouth < .01) smoothMouth = 0;
        motion.current = { speaking: true, mouthOpen: smoothMouth, amplitude, timeline, text: value,
          playbackTime: Math.max(0, (context.currentTime - playbackStarted) * 1000) };
        if (now - lastDebug > 100) {
          lastDebug = now;
          setDebug({ tts: 'READY', audio: 'PLAYING', amplitude });
        }
        session.frame = requestAnimationFrame(analyse);
      };
      const finished = new Promise(resolve => { session.finish = resolve; });
      source.onended = () => {
        if (resources.current === session) {
          session.finish({ ok: true, ttsSeconds });
          // Keep one running context for the next queued sentence; close it on explicit Stop.
          if (options.keepContext) primed.current = context;
          else context.close().catch(() => {});
          resources.current = null;
          cancelAnimationFrame(session.frame);
          source.disconnect(); analyser.disconnect(); context.onstatechange = null;
          motion.current = emptyMotion();
          setPhase('idle'); setDebug({ tts: 'READY', audio: 'READY', amplitude: 0 });
        }
      };
      context.onstatechange = () => {
        if (resources.current === session && context.state === 'suspended') {
          stop();
          setError('Audio was interrupted. Press Speak to play again.');
        }
      };
      playbackStarted = context.currentTime;
      motion.current = { speaking: true, mouthOpen: 0, amplitude: 0, timeline, playbackTime: 0, text: value };
      source.start();
      options.onStart?.({ ttsSeconds, playbackStartSeconds: (performance.now() - requestedAt) / 1000 });
      setPhase('speaking');
      setDebug({ tts: 'READY', audio: 'PLAYING', amplitude: 0 });
      session.frame = requestAnimationFrame(analyse);
      return await finished;
    } catch (failure) {
      if (token !== sequence.current || !mounted.current) return;
      cleanup();
      setPhase('error');
      setDebug({ tts: stage === 'tts' ? 'ERROR' : 'READY', audio: stage === 'audio' ? 'ERROR' : 'READY', amplitude: 0 });
      setError(failure.name === 'AbortError' ? 'Voice generation timed out. Please try again.' :
        failure instanceof TypeError ? 'Cannot reach the backend. Start the FastAPI server and try again.' : failure.message);
      return { ok: false, error: failure.message };
    }
  }, [avatarId, cleanup, prepare, stop]);

  return { phase, error, debug, motion, speak, prepare, stop, unlock };
}
