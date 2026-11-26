import { useCallback, useEffect, useRef, useState } from 'react';

// Hands-free listening: detects when the person starts and stops talking and hands a 16 kHz WAV
// of that utterance to `onUtterance`. Audio runs in an AudioWorklet (off the UI thread). The
// voice detector is energy based with an adaptive noise floor: no model download, cheap on a Pi.
const TARGET_RATE = 16000;
const PRE_ROLL_MS = 400;      // keep the start of the first word
const START_FRAMES = 4;       // ~170 ms of voice before we call it speech
const MIN_SPEECH_MS = 350;    // ignore coughs and clicks
const MAX_SPEECH_MS = 15000;  // one turn at most
const COOLDOWN_MS = 900;      // after the avatar stops, let its voice and the room go quiet first
const MIN_VOICED_MS = 180;    // real speech has this much clearly-loud audio; fan hum and clicks do not
const MAX_FLOOR = .015;       // the noise estimate may never rise so high that normal speech is ignored

const WORKLET = `class Tap extends AudioWorkletProcessor {
  constructor(){super();this.buf=new Float32Array(2048);this.n=0;}
  process(inputs){const ch=inputs[0]&&inputs[0][0];if(ch){for(let i=0;i<ch.length;i++){this.buf[this.n++]=ch[i];
    if(this.n===this.buf.length){this.port.postMessage(this.buf.slice(0));this.n=0;}}}return true;}
}
registerProcessor('living-frame-tap', Tap);`;

function downsample(input, rate) {
  const ratio = rate / TARGET_RATE, length = Math.floor(input.length / ratio), out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const start = Math.floor(i * ratio), end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0; for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

export function encodeWav(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const view = new DataView(new ArrayBuffer(44 + total * 2));
  const text = (offset, s) => { for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i)); };
  text(0, 'RIFF'); view.setUint32(4, 36 + total * 2, true); text(8, 'WAVE'); text(12, 'fmt ');
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, TARGET_RATE, true); view.setUint32(28, TARGET_RATE * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, total * 2, true);
  let offset = 44;
  for (const chunk of chunks) for (const s of chunk) { view.setInt16(offset, Math.max(-1, Math.min(1, s)) * 0x7fff, true); offset += 2; }
  return new Blob([view], { type: 'audio/wav' });
}

export function useHandsFree({ enabled, busy, paused, endSilenceMs = 800, allowInterrupt = false, onUtterance, onInterrupt, device = '' }) {
  const [state, setState] = useState('off');   // off | starting | listening | hearing | waiting | paused | error
  const [level, setLevel] = useState(0);
  const [error, setError] = useState('');
  const live = useRef({ busy, paused, endSilenceMs, allowInterrupt, onUtterance, onInterrupt });
  live.current = { busy, paused, endSilenceMs, allowInterrupt, onUtterance, onInterrupt };
  const idleSince = useRef(0);
  useEffect(() => { if (!busy) idleSince.current = performance.now(); }, [busy]);

  const stopAll = useRef(() => {});
  const vadRef = useRef(null);
  const disable = useCallback(() => { stopAll.current(); setState('off'); setLevel(0); }, []);

  useEffect(() => {
    if (!enabled) { stopAll.current(); setState('off'); setLevel(0); return; }
    let disposed = false, stream, context, node, url;
    const vad = { floor: .01, voiced: 0, inSpeech: false, silenceMs: 0, speechMs: 0, voicedMs: 0, peak: 0, lastPeak: 0, chunks: [], preRoll: [], preMs: 0, loud: 0, lastUi: 0, shown: '' };
    vadRef.current = vad;
    const show = next => { if (vad.shown !== next) { vad.shown = next; setState(next); } };
    const reset = () => { vad.inSpeech = false; vad.chunks = []; vad.speechMs = 0; vad.silenceMs = 0; vad.voiced = 0; vad.voicedMs = 0; vad.peak = 0; };
    stopAll.current = () => {
      disposed = true;
      try { node?.port && (node.port.onmessage = null); node?.disconnect(); } catch { /* already gone */ }
      stream?.getTracks().forEach(t => t.stop());
      if (context && context.state !== 'closed') context.close().catch(() => {});
      if (url) URL.revokeObjectURL(url);
    };
    (async () => {
      try {
        setError(''); show('starting');
        if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) throw new Error('This browser cannot listen hands-free. Try Chrome or Edge.');
        // Echo cancellation is needed only for interrupting (the mic is paused while the avatar
        // speaks otherwise). On Windows it also switches the mic to "communications" mode, which
        // by default turns every other sound down by 80% — the avatar would become almost silent.
        stream = await navigator.mediaDevices.getUserMedia({ audio: {
          ...(device ? { deviceId: { exact: device } } : {}), channelCount: 1,
          echoCancellation: !!live.current.allowInterrupt, noiseSuppression: true, autoGainControl: true } });
        if (disposed) { stream.getTracks().forEach(t => t.stop()); return; }
        context = new (window.AudioContext || window.webkitAudioContext)();
        url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
        await context.audioWorklet.addModule(url);
        if (disposed) return;
        node = new AudioWorkletNode(context, 'living-frame-tap');
        const mute = context.createGain(); mute.gain.value = 0;
        context.createMediaStreamSource(stream).connect(node); node.connect(mute); mute.connect(context.destination);
        await context.resume();
        node.port.onmessage = ({ data }) => {
          if (disposed) return;
          let power = 0; for (const s of data) power += s * s;
          const rms = Math.sqrt(power / data.length), frameMs = data.length / context.sampleRate * 1000, now = performance.now();
          if (now - vad.lastUi > 120) { vad.lastUi = now; setLevel(Math.min(1, rms * 12)); }
          const { busy, paused, endSilenceMs, allowInterrupt } = live.current;
          const startThreshold = Math.max(.012, vad.floor * 3.2), keepThreshold = Math.max(.008, vad.floor * 2);
          const pcm = downsample(data, context.sampleRate);
          if (busy) {
            // The avatar is thinking or talking: don't record its own voice. Optionally allow a
            // clearly louder, sustained voice to interrupt it.
            reset();
            if (allowInterrupt && live.current.onInterrupt) {
              vad.loud = rms > Math.max(.05, vad.floor * 6) ? vad.loud + 1 : 0;
              if (vad.loud * frameMs > 350) { vad.loud = 0; live.current.onInterrupt(); }
            }
            show('waiting'); return;
          }
          if (paused) { reset(); show('paused'); return; }
          if (now - idleSince.current < COOLDOWN_MS) { show('listening'); return; }
          if (!vad.inSpeech) {
            vad.preRoll.push(pcm); vad.preMs += frameMs;
            while (vad.preMs > PRE_ROLL_MS && vad.preRoll.length > 1) { vad.preRoll.shift(); vad.preMs -= frameMs; }
            if (rms > startThreshold) vad.voiced++;
            else { vad.voiced = 0; if (rms < vad.floor * 3) vad.floor = Math.max(.002, vad.floor * .95 + rms * .05); }
            if (vad.voiced >= START_FRAMES) {
              vad.inSpeech = true; vad.chunks = [...vad.preRoll]; vad.speechMs = vad.preMs; vad.silenceMs = 0;
              vad.preRoll = []; vad.preMs = 0;
            }
            show(vad.inSpeech ? 'hearing' : 'listening'); return;
          }
          vad.chunks.push(pcm); vad.speechMs += frameMs;
          // "Quiet" is relative to how loud this person actually spoke, so steady room noise
          // (fan, traffic) cannot keep a recording open until the 15 s limit.
          vad.peak = Math.max(vad.peak * .995, rms);
          if (rms > startThreshold) vad.voicedMs += frameMs;
          vad.silenceMs = rms < Math.max(keepThreshold, vad.peak * .18) ? vad.silenceMs + frameMs : 0;
          if (vad.silenceMs >= endSilenceMs || vad.speechMs >= MAX_SPEECH_MS) {
            const spoken = vad.speechMs - vad.silenceMs, chunks = vad.chunks, voiced = vad.voicedMs, peak = vad.peak;
            reset();
            vad.lastPeak = peak;
            // Only clear speech goes to recognition: every false trigger would keep Whisper busy
            // for seconds, and the person's real sentence would be missed meanwhile.
            if (spoken >= MIN_SPEECH_MS && voiced >= MIN_VOICED_MS && peak >= Math.max(.02, vad.floor * 3))
              live.current.onUtterance?.(encodeWav(chunks), spoken / 1000);
            else vad.floor = Math.min(MAX_FLOOR, Math.max(vad.floor, peak / 6));
            show('listening');
          }
        };
      } catch (failure) {
        if (disposed) return;
        stopAll.current();
        setError(failure?.name === 'NotAllowedError' ? 'Microphone permission was denied.' : failure?.message || 'Microphone unavailable.');
        setState('error');
      }
    })();
    return () => stopAll.current();
  }, [enabled, device]);

  // Recognition found no words in the last recording: treat that sound level as room noise.
  const falseTrigger = useCallback(() => {
    const vad = vadRef.current;
    // Only a small, capped step: a big jump made the microphone deaf to normal speech.
    if (vad) vad.floor = Math.min(MAX_FLOOR, Math.max(vad.floor * 1.15, vad.lastPeak / 6));
  }, []);
  return { state, level, error, disable, falseTrigger };
}
