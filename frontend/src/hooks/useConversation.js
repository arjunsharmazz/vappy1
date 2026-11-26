import { useCallback, useEffect, useRef, useState } from 'react';

// Devanagari so the Hindi voice says them naturally (Roman text is read with an English accent).
const FILLERS = ['हम्म।', 'अच्छा।', 'हाँ।', 'एक सेकंड।', 'हम्म, अच्छा।'];
const FILLER_DELAY_MS = 1400;

export function useConversation(avatarId, speech, { onEmotion } = {}) {
  const emotionRef = useRef(onEmotion); emotionRef.current = onEmotion;
  const [phase, setPhase] = useState('idle');
  // What started the current turn: the person ('speech'), the avatar noticing something
  // ('observation') or a greeting ('greeting') — shown in the status panel.
  const [kind, setKind] = useState('speech');
  const [messages, setMessages] = useState([]);
  const [error, setError] = useState('');
  const [metrics, setMetrics] = useState(null);
  const [responseLength, setResponseLength] = useState('short');
  const [language, setLanguage] = useState('auto');
  const session = useRef(crypto.randomUUID());
  const current = useRef(null);
  const speechRef = useRef(speech); speechRef.current = speech;
  const stop = useCallback(() => {
    const run = current.current; current.current = null;
    if (run) {
      run.abort.abort(); run.queue.length = 0;
      fetch(`/avatar/${avatarId}/conversation/cancel`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: session.current, turn_id: run.id }),
      }).catch(() => {});
    }
    speechRef.current.stop(); setPhase('idle');
  }, [avatarId]);
  useEffect(() => () => stop(), [stop]);

  // kind 'observation': nobody spoke; the avatar reacts to a feeling it sees (text = its name).
  const request = useCallback(async (text, blob, recordingDuration, kind = 'speech') => {
    const observing = kind === 'observation';
    setKind(kind);
    if (!avatarId) return;
    stop(); speechRef.current.unlock(); setError(''); setMetrics(null);
    const run = { id: crypto.randomUUID(), abort: new AbortController(), queue: [],
      started: performance.now(), pump: null, failedVoice: false,
      stats: { recording_duration_seconds: recordingDuration || 0, tts_chunks_seconds: [] }, answer: '' };
    current.current = run;
    const active = () => current.current === run;
    // People say "hmm…" while they think. If the answer is not ready quickly, say a short filler
    // (its audio is cached after the first time, so it starts instantly). The real reply waits
    // for the filler to finish instead of cutting it off.
    setTimeout(() => {
      if (observing || !active() || run.answerStarted || Math.random() > .7) return;
      run.filler = speechRef.current.speak(FILLERS[Math.floor(Math.random() * FILLERS.length)], { keepContext: true }).catch(() => {});
    }, FILLER_DELAY_MS);
    // Start synthesizing the next two sentences right away (in order), while earlier ones play.
    const prefetch = () => {
      for (const item of run.queue.slice(0, 2)) {
        if (!item.ready) {
          item.ready = speechRef.current.prepare(item.text, run.abort.signal);
          item.ready.catch(() => {});  // a failure surfaces when that sentence is spoken
        }
      }
    };
    const pump = () => {
      if (run.pump || !active() || run.failedVoice) return;
      run.pump = (async () => {
        if (run.filler) { await run.filler; run.filler = null; }
        while (active() && run.queue.length && !run.failedVoice) {
          prefetch();
          const chunk = run.queue.shift();
          prefetch();
          setPhase('generating');
          const onStart = timing => {
            if (!active()) return;
            setPhase('speaking');
            run.stats.tts_chunks_seconds.push(timing.ttsSeconds);
            run.stats.time_until_avatar_speaks_seconds ??= (performance.now() - run.started) / 1000;
            run.stats.total_including_recording_seconds = run.stats.time_until_avatar_speaks_seconds + run.stats.recording_duration_seconds;
            setMetrics({ ...run.stats });
          };
          let result = await speechRef.current.speak(chunk.text, { keepContext: true, prepared: chunk.ready, onStart });
          if (!active()) return;
          // One sentence failing (voice engine busy, a network hiccup) must not silence the rest of
          // the reply: try that sentence once more, and if it still fails skip only it.
          if (!result?.ok) result = await speechRef.current.speak(chunk.text, { keepContext: true, onStart });
          if (!active()) return;
          if (!result?.ok) {
            run.voiceFailures = (run.voiceFailures || 0) + 1;
            if (run.voiceFailures >= 3) {
              run.failedVoice = true; run.queue.length = 0;
              setError('Voice playback failed. The response is available as text.');
            }
          } else run.voiceFailures = 0;
        }
        if (active()) setPhase('thinking');
      })().finally(() => { run.pump = null; });
    };
    try {
      if (blob) {
        setPhase('transcribing');
        const body = new FormData(); body.append('file', blob, 'recording.audio'); body.append('language', language);
        const response = await fetch(`/avatar/${avatarId}/listen`, { method: 'POST', body, signal: run.abort.signal });
        const result = await response.json();
        if (!response.ok) {
          const failure = new Error(typeof result.detail === 'string' ? result.detail : 'Speech recognition failed. Please retry.');
          failure.status = response.status; throw failure;
        }
        if (!active()) return;
        text = result.text;
        run.stats.stt_seconds = result.stt_seconds;
        run.stats.audio_duration_seconds = result.audio_duration_seconds;
        run.stats.stt_resources = result.resources;
        run.stats.stt_confidence = result.confidence;
      }
      if (!text?.trim()) throw new Error('Please record or type a message.');
      if (text.length > 500) throw new Error('That message is too long. Please use a shorter recording.');
      setMessages(old => [...old.slice(-6), ...(observing ? [] : [{ role: 'YOU', text }]), { role: 'AVATAR', text: '' }]);
      setPhase('thinking');
      const response = await fetch(`/avatar/${avatarId}/conversation`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, signal: run.abort.signal,
        body: JSON.stringify({ session_id: session.current, turn_id: run.id, text, response_length: responseLength, kind,
          ...(blob && Number.isFinite(run.stats.stt_confidence) ? { stt_confidence: Math.max(-20, Math.min(0, run.stats.stt_confidence)) } : {}) }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(typeof result?.detail === 'string' ? result.detail : 'Local AI unavailable. Please retry.');
      }
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let pending = '', done = false;
      try {
        while (active()) {
          const { value, done: ended } = await reader.read();
          pending += decoder.decode(value, { stream: !ended });
          const lines = pending.split('\n'); pending = lines.pop();
          for (const line of lines) {
            if (!line.trim() || !active()) continue;
            const item = JSON.parse(line);
            if (item.type === 'token') {
              run.answer += item.text;
              setMessages(old => [...old.slice(0, -1), { role: 'AVATAR', text: run.answer }]);
            } else if (item.type === 'chunk' && !run.failedVoice) {
              run.answerStarted = true; run.queue.push({ text: item.text }); prefetch(); pump();
            } else if (item.type === 'emotion') emotionRef.current?.(item.name);
            else if (item.type === 'done') { Object.assign(run.stats, item.metrics); done = true; }
            else if (item.type === 'error') throw new Error(item.message);
          }
          if (ended) break;
        }
      } finally { reader.releaseLock(); }
      if (!active()) return;
      if (!done) throw new Error('The local AI response was interrupted. Please retry.');
      if (run.pump) await run.pump;
      if (active()) {
        run.stats.turn_finished_seconds = (performance.now() - run.started) / 1000;
        setMetrics({ ...run.stats }); setPhase('idle');
        current.current = null; speechRef.current.stop();
      }
    } catch (failure) {
      if (!active()) return;
      // A recording with no words (noise, a cough) is not an error for the person: just listen again.
      if (blob && failure.status === 422) { stop(); return { noSpeech: true }; }
      stop(); setError(failure.message || 'Conversation failed. Please retry.');
    }
  }, [avatarId, language, responseLength, stop]);

  const clear = useCallback(async () => {
    stop(); setError('');
    try {
      if (avatarId) {
        const response = await fetch(`/avatar/${avatarId}/conversation/clear`, { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: session.current }) });
        if (!response.ok) throw new Error('Could not clear conversation. Please retry.');
      }
      setMessages([]); setMetrics(null);
    } catch (failure) { setError(failure.message); }
  }, [avatarId, stop]);
  // The avatar speaks on its own (e.g. greeting someone who walked up). Skipped when busy;
  // Stop and hands-free pausing work exactly as for a normal reply.
  const announce = useCallback(async text => {
    if (!avatarId || !text || current.current) return;
    const run = { id: crypto.randomUUID(), abort: new AbortController(), queue: [] };
    current.current = run;
    setError(''); setKind('greeting'); setMessages(old => [...old.slice(-6), { role: 'AVATAR', text }]);
    setPhase('generating');
    await speechRef.current.speak(text, { keepContext: true, onStart: () => { if (current.current === run) setPhase('speaking'); } });
    if (current.current === run) { current.current = null; setPhase('idle'); speechRef.current.stop(); }
  }, [avatarId]);
  const observe = useCallback(name => request(name, null, 0, 'observation'), [request]);
  return { phase, kind, messages, error, metrics, stop, clear, request, announce, observe, responseLength, setResponseLength, language, setLanguage };
}
