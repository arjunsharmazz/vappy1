"""Speech. Microsoft neural voices through edge-tts (very natural Hindi/Hinglish, needs internet)
first; offline Piper (Hindi neural voices, Windows + Raspberry Pi) when there is no internet;
Windows SAPI as the last fallback. Validate actual PCM before publishing an audio URL."""
import asyncio
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
import wave

import numpy as np
from fastapi import HTTPException

from ..settings import get_settings, current_gender, persona_gender
from .gender import avatar_gender

_SERVICE_DIR = Path(__file__).resolve().parent
_SYNTHESIS_LOCK = threading.Lock()
MAX_WAV_BYTES = 25 * 1024 * 1024
_CACHE_NAMESPACE = uuid5(NAMESPACE_URL, "living-frame-tts-v1")
# A sentence takes ~1 s to synthesize; a queued reply waits for a short filler ("Hmm…")
# to finish instead of failing with "busy".
# With the offline voice the next sentences queue behind the current one (one at a time on this
# CPU); waiting only 8 s returned "busy" and the rest of the reply went unspoken. Wait instead.
LOCK_WAIT_SECONDS = 40


def validate_wav(path: Path):
    if not path.is_file() or not 44 < path.stat().st_size <= MAX_WAV_BYTES:
        raise ValueError("Missing, empty or oversized WAV")
    with wave.open(str(path), "rb") as wav:
        channels, width, rate, count = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
        if wav.getcomptype() != "NONE" or width != 2 or channels not in (1, 2) or not 8000 <= rate <= 48000:
            raise ValueError("Unsupported PCM format")
        if not .05 < count / rate <= 180:
            raise ValueError("Invalid audio duration")
        frames = wav.readframes(count)
        if len(frames) != count * channels * width:
            raise ValueError("Truncated WAV")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768
    rms = float(np.sqrt(np.mean(samples * samples)))
    peak = float(np.max(np.abs(samples)))
    if rms < .0003 or peak < .002:
        raise ValueError("Speech output is silent")
    return {"duration_seconds": round(count / rate, 3), "sample_rate": rate,
            "channels": channels, "rms": round(rms, 6), "peak": round(peak, 6),
            "size_bytes": path.stat().st_size}


_PIPER = {"path": None, "voice": None}
PIPER_DIR = Path(__file__).resolve().parents[3] / ".tools" / "models" / "piper"


PIPER_BY_GENDER = {"female": "hi_IN-priyamvada-medium", "male": "hi_IN-pratham-medium"}


def piper_model():
    # The avatar's gender picks the offline voice when that voice is installed.
    name = PIPER_BY_GENDER.get(current_gender.get() or "") or get_settings()["tts"]["voice"]
    if not (PIPER_DIR / f"{name}.onnx").is_file():
        name = get_settings()["tts"]["voice"]
    path = PIPER_DIR / f"{name}.onnx"
    return path if path.is_file() and path.with_suffix(".onnx.json").is_file() else None


# Online voice: one failure (no internet) skips it for a while, so every sentence does not wait
# for a network timeout before the offline voice speaks.
EDGE_RETRY_SECONDS = 30
_EDGE = {"failed_at": 0.0}


def edge_voice():
    cfg = get_settings()
    # A man's photo speaks with a male voice, a woman's with a female one. A voice written in
    # settings.toml (edge_voice) is a deliberate override for every avatar.
    return cfg["tts"]["edge_voice"] or ("hi-IN-SwaraNeural" if persona_gender() == "female" else "hi-IN-MadhurNeural")


def _edge_usable():
    if get_settings()["tts"]["provider"] not in ("auto", "edge"):
        return False
    if time.monotonic() - _EDGE["failed_at"] < EDGE_RETRY_SECONDS:
        return False
    try:
        import edge_tts  # noqa: F401
        import av  # noqa: F401
        return True
    except ImportError:
        return False


def _run_edge(text, output):
    """Microsoft neural voice (MP3 over the network), decoded to 24 kHz mono 16-bit WAV."""
    import av
    import edge_tts
    cfg = get_settings()["tts"]

    words = []

    async def fetch():
        audio = bytearray()
        # Word timings come with the audio: the mouth can follow the real words, not a guess.
        communicate = edge_tts.Communicate(text, edge_voice(), rate=cfg["edge_rate"], pitch=cfg["edge_pitch"],
                                           boundary="WordBoundary")
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10000  # 100 ns units → ms
                words.append({"start": round(start), "end": round(start + chunk["duration"] / 10000), "text": chunk["text"]})
        return bytes(audio)

    async def bounded():
        return await asyncio.wait_for(fetch(), max(2, cfg["edge_timeout_seconds"]))

    mp3 = asyncio.run(bounded())
    if not mp3:
        raise ValueError("Online voice returned no audio")
    pcm = bytearray()
    resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)
    with av.open(io.BytesIO(mp3)) as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                pcm += bytes(out.planes[0])[:out.samples * 2]
    for out in resampler.resample(None):
        pcm += bytes(out.planes[0])[:out.samples * 2]
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(bytes(pcm))
    return words


def _provider():
    choice = get_settings()["tts"]["provider"]
    if choice in ("auto", "piper") and piper_model() is not None:
        try:
            import piper  # noqa: F401
            return "piper"
        except ImportError:
            if choice == "piper":
                logging.warning("piper-tts is not installed; falling back to Windows voices")
    return "sapi"


def _load_piper():
    from piper import PiperVoice
    model = piper_model()
    if _PIPER["path"] != model:
        logging.info("Loading Piper voice %s", model.stem)
        _PIPER["voice"], _PIPER["path"] = PiperVoice.load(str(model)), model


def warm_up():
    """Load the voice at start-up so the first reply is not ~9 s late (measured)."""
    if _provider() != "piper":
        return
    with _SYNTHESIS_LOCK:
        _load_piper()


def _run_piper(text, output):
    """In-process neural TTS; the voice (~63 MB) stays loaded after the first sentence."""
    from piper import SynthesisConfig
    _load_piper()
    speed = max(.5, min(2.0, get_settings()["tts"]["speed"]))
    with wave.open(str(output), "wb") as wav:
        _PIPER["voice"].synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1 / speed))


def _run_pyttsx3(text, output):
    rate = str(get_settings()["tts"]["rate_wpm"])
    subprocess.run([sys.executable, str(_SERVICE_DIR / "tts_worker.py"), str(output), rate],
                   input=text, encoding="utf-8", capture_output=True, check=True,
                   timeout=45, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _run_windows_fallback(text, output):
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(_SERVICE_DIR / "tts_fallback.ps1"), "-OutputFile", str(output)],
                   input=json.dumps({"text": text}, ensure_ascii=True), encoding="utf-8",
                   capture_output=True, check=True, timeout=45,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _words(path):
    """Word timings saved next to a WAV ([] when the voice gave none)."""
    try:
        words = json.loads(path.with_suffix(".words.json").read_text(encoding="utf-8"))
        return words if isinstance(words, list) else []
    except (OSError, ValueError):
        return []


def _cached(avatar_id, speech_id, root):
    cached = root / avatar_id / "audio" / f"{speech_id}.wav"
    if cached.is_file():
        try:
            info = validate_wav(cached)
            return {"success": True, "speech_id": speech_id, "audio_url": f"/avatar/{avatar_id}/audio/{speech_id}",
                    "message": "Speech reused", "tts_engine": "cache", "words": _words(cached), **info}
        except (OSError, ValueError, wave.Error, EOFError):
            cached.unlink(missing_ok=True)
    return None


def _generate_edge(avatar_id, text, root):
    """Online voice without the offline-engine lock, so the next sentence can be prepared while
    the current one plays. Returns None (and pauses the online voice) when it fails."""
    cfg = get_settings()["tts"]
    speech_id = str(uuid5(_CACHE_NAMESPACE, f"edge:{edge_voice()}:{cfg['edge_rate']}:{cfg['edge_pitch']}|{text}"))
    reused = _cached(avatar_id, speech_id, root)
    if reused:
        return reused
    folder = root / avatar_id / "audio"
    folder.mkdir(parents=True, exist_ok=True)
    pending = folder / f"{speech_id}.{uuid4().hex}.pending.wav"
    try:
        words = _run_edge(text, pending) or []
        info = validate_wav(pending)
        target = folder / f"{speech_id}.wav"
        target.with_suffix(".words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        pending.replace(target)
        return {"success": True, "speech_id": speech_id, "audio_url": f"/avatar/{avatar_id}/audio/{speech_id}",
                "message": "Speech generated", "tts_engine": "edge:" + edge_voice(), "words": words, **info}
    except Exception as error:
        _EDGE["failed_at"] = time.monotonic()
        logging.warning("Online voice unavailable (%s); using the offline voice for %d s",
                        type(error).__name__, EDGE_RETRY_SECONDS)
        return None
    finally:
        pending.unlink(missing_ok=True)


def generate_speech(avatar_id: str, text: str, root: Path):
    token = current_gender.set(avatar_gender(avatar_id, root))
    try:
        return _generate_speech(avatar_id, text, root)
    finally:
        current_gender.reset(token)


def _generate_speech(avatar_id: str, text: str, root: Path):
    if _edge_usable():
        result = _generate_edge(avatar_id, text, root)
        if result:
            return result
    provider = _provider()
    if provider == "sapi" and sys.platform != "win32":
        raise HTTPException(503, "No offline voice available. Install piper-tts and a voice in .tools/models/piper.")
    # Same text + voice settings → same id, so repeated phrases ("Hmm…", greetings, ready-made
    # replies) are served instantly from the earlier WAV instead of being synthesized again.
    cfg = get_settings()["tts"]
    voice_key = f"piper:{piper_model().stem if piper_model() else cfg['voice']}:{cfg['speed']}" if provider == "piper" else f"sapi:{cfg['rate_wpm']}"
    speech_id = str(uuid5(_CACHE_NAMESPACE, f"{voice_key}|{text}"))
    reused = _cached(avatar_id, speech_id, root)
    if reused:
        return reused
    if not _SYNTHESIS_LOCK.acquire(timeout=LOCK_WAIT_SECONDS):
        raise HTTPException(429, "The local voice engine is busy. Please try again shortly.")
    pending = None
    try:
        folder = root / avatar_id / "audio"
        folder.mkdir(parents=True, exist_ok=True)
        pending = folder / f"{speech_id}.pending.wav"
        target = folder / f"{speech_id}.wav"
        backend = "pyttsx3-sapi5"
        info = None
        if provider == "piper":
            try:
                _run_piper(text, pending)
                info = validate_wav(pending)
                backend = "piper:" + cfg["voice"]
            except Exception:
                logging.exception("Piper could not synthesize this text; trying Windows voices")
                pending.unlink(missing_ok=True)
                if sys.platform != "win32":
                    raise HTTPException(503, "The offline voice failed. Please try again.")
        if info is None:
            try:
                _run_pyttsx3(text, pending)
                info = validate_wav(pending)
            except (OSError, ValueError, wave.Error, EOFError, subprocess.SubprocessError):
                logging.warning("pyttsx3 did not produce usable audio; trying installed Windows System.Speech")
                pending.unlink(missing_ok=True)
                backend = "windows-system-speech"
                _run_windows_fallback(text, pending)
                info = validate_wav(pending)
        pending.replace(target)
        return {"success": True, "speech_id": speech_id,
                "audio_url": f"/avatar/{avatar_id}/audio/{speech_id}",
                "message": "Speech generated", "tts_engine": backend, **info}
    except (OSError, ValueError, wave.Error, EOFError, subprocess.SubprocessError):
        logging.exception("Local speech generation failed")
        raise HTTPException(503, "Windows could not generate valid speech. Check that a Windows speech voice is installed and try again.")
    finally:
        try:
            if pending is not None:
                pending.unlink(missing_ok=True)
        finally:
            _SYNTHESIS_LOCK.release()


def audio_path(avatar_id: str, speech_id: str, root: Path):
    try:
        if str(UUID(speech_id)) != speech_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(400, "Invalid speech_id.")
    path = root / avatar_id / "audio" / f"{speech_id}.wav"
    if not path.is_file():
        raise HTTPException(404, "Speech audio not found.")
    try:
        validate_wav(path)
    except (OSError, ValueError, wave.Error, EOFError):
        raise HTTPException(422, "Speech audio is empty, silent or corrupted. Generate it again.")
    return path
