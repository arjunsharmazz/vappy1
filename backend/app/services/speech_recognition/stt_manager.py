import gc
import logging
import re
from pathlib import Path
import threading
import time

from .base_stt import SpeechRecognitionEngine
from .audio_preprocessor import decode_recording
from ...settings import get_settings

log = logging.getLogger('audio.stt')

# Whisper "hears" these in silence or noise. They are dropped unless clearly spoken.
HALLUCINATIONS = re.compile(r'^(thank you|thanks|thank you for watching|thanks for watching|please subscribe|'
                            r'subscribe|you|bye|okay|so|uh|um|hmm|music|applause|धन्यवाद|शुक्रिया)[.!? ]*$', re.I)
MIN_LOGPROB = -1.4         # below this a segment is guesswork; between this and min_confidence we ask to repeat
DEBUG_DIR = Path(__file__).resolve().parents[4] / 'avatar_data' / 'debug_audio'
DEBUG_KEEP = 20


def save_debug_audio(audio, label):
    """Only with stt.log_transcripts: keep the last few recordings locally to tune recognition."""
    import wave
    import numpy as np
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBUG_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}-{label}.wav"
        with wave.open(str(path), 'wb') as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
            wav.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
        for old in sorted(DEBUG_DIR.glob('*.wav'))[:-DEBUG_KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        log.warning('Could not save a debug recording', exc_info=True)
LOCK_WAIT_SECONDS = 20     # a sentence takes ~3-8 s on a slow CPU
HALLUCINATION_LOGPROB = -0.45


class FasterWhisperEngine(SpeechRecognitionEngine):
    def __init__(self):
        cfg = get_settings()['stt']
        self.model = None
        self.path = Path(cfg['model_path'])
        self.compute_type = cfg['compute_type']
        self.threads = cfg['threads']
        self.beam_size = cfg['beam_size']

    def load(self):
        if self.model is None:
            if not (self.path / 'model.bin').is_file():
                log.error('Whisper model not found at %s', self.path)
                raise RuntimeError('Local speech model unavailable. Run the Phase 6 setup command.')
            from faster_whisper import WhisperModel
            log.info('Loading Whisper model %s (%s, threads=%d)', self.path.name, self.compute_type, self.threads)
            self.model = WhisperModel(str(self.path), device='cpu', compute_type=self.compute_type,
                                      cpu_threads=self.threads, num_workers=1, local_files_only=True)

    def transcribe(self, audio_path, language=None, hotwords=None):
        audio = decode_recording(audio_path)
        self.load()

        debug = get_settings()['stt']['log_transcripts']

        def run(lang):
            # Hotwords bias spelling of names; a full initial_prompt would leak into the text.
            # Silero VAD threshold 0.35 (default 0.5): softer Hindi speech was being cut away.
            segments, info = self.model.transcribe(audio, task='transcribe', language=lang,
                beam_size=self.beam_size, condition_on_previous_text=False, vad_filter=True,
                vad_parameters={'min_silence_duration_ms': 400, 'threshold': 0.35}, hotwords=hotwords or None)
            segments = list(segments)
            # Drop only what is clearly not speech. Merely unsure text is kept: the conversation
            # then asks the person to repeat (stt.min_confidence) instead of ignoring them.
            kept = [s for s in segments if not (s.no_speech_prob > .75 and s.avg_logprob < -.7)
                    and s.avg_logprob > MIN_LOGPROB]
            if debug:
                for s in segments:
                    log.info('  segment %r no_speech=%.2f confidence=%.2f %s', s.text.strip(), s.no_speech_prob,
                             s.avg_logprob, 'kept' if s in kept else 'DROPPED')
            text = ' '.join(s.text.strip() for s in kept).strip()
            confidence = min((s.avg_logprob for s in kept), default=-9.0)
            return text, info, confidence

        text, info, confidence = run(language)
        if language is None and info.language == 'ur':
            # Whisper often labels spoken Hindi/Hinglish as Urdu and writes Urdu script,
            # which neither the replies nor the English voice can use. Redo it as Hindi.
            log.info('Speech detected as Urdu; transcribing again as Hindi')
            text, info, confidence = run('hi')
        if text and HALLUCINATIONS.match(text) and confidence < HALLUCINATION_LOGPROB:
            log.info('Ignored a likely Whisper hallucination (confidence %.2f)', confidence)
            text = ''
        if debug:
            save_debug_audio(audio, 'heard' if text else 'empty')
        if not text:
            if debug:
                log.info('No words found in %.1fs of audio (peak %.3f)', len(audio) / 16000, float(abs(audio).max()))
            raise ValueError('No speech detected. Please try again.')
        return {'text': text, 'language': info.language, 'confidence': round(confidence, 3),
                'audio_duration_seconds': len(audio) / 16000}

    def unload(self):
        self.model = None
        gc.collect()


class STTManager:
    def __init__(self, engine=None):
        self.engine = engine or FasterWhisperEngine()
        self.lock = threading.Lock()

    def transcribe(self, path, language=None, hotwords=None):
        # Wait for the previous recording (e.g. one from a reloaded page that is still being
        # transcribed) instead of failing: the person should never see "busy".
        if not self.lock.acquire(timeout=LOCK_WAIT_SECONDS):
            raise RuntimeError('Speech recognition is busy. Please retry shortly.')
        started = time.perf_counter()
        try:
            result = self.engine.transcribe(path, language, hotwords)
            result['stt_seconds'] = time.perf_counter() - started
            log.info('Transcribed %.1fs of audio in %.1fs (%s, confidence %.2f)', result['audio_duration_seconds'],
                     result['stt_seconds'], result['language'], result['confidence'])
            if get_settings()['stt']['log_transcripts']:
                # Opt-in, local log only: helps tune recognition for a real voice.
                log.info('Heard: %s', result['text'])
            return result
        finally:
            self.lock.release()

    def unload(self):
        with self.lock:
            self.engine.unload()

    def warm_up(self):
        # Held under the lock, so a recording that arrives meanwhile simply waits.
        with self.lock:
            self.engine.load()


manager = STTManager()
