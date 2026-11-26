import json
from typing import Literal
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .settings import get_settings, public_settings
from .logging_setup import setup_logging
setup_logging(get_settings()["logging"]["level"])
from .config import AVATAR_DATA, MAX_UPLOAD_BYTES, UPLOADS
from .imaging import process_image
from .services.avatar_store import create_avatar, read_avatar
from .services.tts_service import generate_speech, audio_path

_settings = get_settings()
logging.getLogger("startup").info("Settings loaded from %s | device profile: %s | threads stt=%d llm=%d",
    _settings["source"], _settings["device"]["resolved_profile"], _settings["stt"]["threads"], _settings["llm"]["threads"])

UPLOADS.mkdir(parents=True, exist_ok=True)
AVATAR_DATA.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="AI Living Frame", version="3.0.0")
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")

from .services.conversation_routes import router as conversation_router
app.include_router(conversation_router)
from .services.neural_avatar.routes import router as neural_router
app.include_router(neural_router)
from .vision.routes import router as vision_router
app.include_router(vision_router)


@app.on_event("startup")
def install_library():
    """Ready-made avatars from avtars/prepared (prepared on a PC) appear in the avatar list."""
    from .services.avatar_library import install_all
    try:
        install_all()
    except Exception:
        logging.getLogger("startup").exception("Could not install the ready-made avatars")


@app.get("/avatar/library")
def avatar_library():
    from .services.avatar_library import listing
    return {"avatars": listing()}


@app.on_event("startup")
def warm_models():
    """Load the voice and speech recognition in the background, so the very first
    conversation turn is as fast as the rest (the first load took ~5-9 s each)."""
    import threading
    from .services.tts_service import warm_up as warm_voice
    from .services.speech_recognition.stt_manager import manager as stt

    jobs = [("voice", warm_voice), ("speech recognition", stt.warm_up)]
    from .services.local_ai.online_llm import online
    if get_settings()["device"]["resolved_profile"] in ("pi4", "pi5") and online.configured():
        # 4 GB Raspberry Pi: with the online voice and listening, the offline Whisper and Piper
        # models are only a fallback — load them when (if) they are needed, not at boot.
        jobs = []

    def run():
        for name, job in jobs:
            try:
                job()
            except Exception:  # a missing model only means it loads (or fails) on first use
                logging.getLogger("startup").warning("Could not preload %s", name, exc_info=True)
    threading.Thread(target=run, name="warm-up", daemon=True).start()

@app.get("/config")
def config():
    # Non-secret settings only (no paths, no keys) for the frontend.
    return public_settings()


@app.get("/health")
def health():
    return {"status": "ok", "device": "cpu"}

def save_avatar(data: bytes, suffix: str):
    encoded, face_detected, details = process_image(data, suffix)
    return create_avatar(encoded, face_detected, details, UPLOADS, AVATAR_DATA)


@app.get("/avatar/{avatar_id}")
def get_avatar(avatar_id: str):
    record, _ = read_avatar(avatar_id, UPLOADS, AVATAR_DATA)
    return record


@app.get("/avatar/{avatar_id}/image")
def get_avatar_image(avatar_id: str):
    _, image = read_avatar(avatar_id, UPLOADS, AVATAR_DATA)
    return FileResponse(image, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@app.post("/avatar/upload")
async def upload_avatar(file: UploadFile):
    try:
        suffix = Path(file.filename or "").suffix.lower()
        # Windows often saves JPEGs as .jfif; the actual bytes are checked in process_image.
        if suffix in {".jfif", ".jpe", ".pjpeg", ".pjp"}:
            suffix = ".jpg"
        if suffix not in {".jpg", ".jpeg", ".png"}:
            raise HTTPException(415, "Please upload a JPG, JPEG or PNG image.")
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if not data:
            raise HTTPException(400, "The uploaded file is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Image must be 10 MB or smaller.")
        return await run_in_threadpool(save_avatar, data, suffix)
    except HTTPException:
        raise
    except Exception:
        logging.exception("Avatar processing failed")
        raise HTTPException(500, "Could not process or save the image. Please try again.")
    finally:
        await file.close()



class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500, strict=True)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value):
        value = value.strip()
        if not value or not any(character.isalnum() for character in value):
            raise ValueError("Please enter text containing words or numbers.")
        if any(ord(character) < 32 and character not in "\n\r\t" for character in value):
            raise ValueError("Text contains unsupported control characters.")
        return value


class VoiceRequest(BaseModel):
    gender: Literal["male", "female"]


@app.post("/avatar/{avatar_id}/voice")
def set_avatar_voice(avatar_id: str, body: VoiceRequest):
    """Switch the avatar between the male and female voice (the photo guess can be wrong)."""
    record, _ = read_avatar(avatar_id, UPLOADS, AVATAR_DATA)
    path = AVATAR_DATA / avatar_id / "avatar.json"
    if not path.is_file():
        raise HTTPException(409, "This older avatar cannot store a voice choice. Please upload the photo again.")
    record["voice_gender"] = body.gender
    pending = path.with_suffix(".pending.json")
    pending.write_text(json.dumps(record, indent=2), encoding="utf-8")
    pending.replace(path)
    return record


@app.post("/avatar/{avatar_id}/speak")
def speak_avatar(avatar_id: str, body: SpeechRequest):
    record, _ = read_avatar(avatar_id, UPLOADS, AVATAR_DATA)
    if not record["face_detected"]:
        raise HTTPException(409, "Please upload a valid face before generating speech.")
    return generate_speech(avatar_id, body.text, AVATAR_DATA)


@app.get("/avatar/{avatar_id}/audio/{speech_id}")
def get_speech_audio(avatar_id: str, speech_id: str):
    read_avatar(avatar_id, UPLOADS, AVATAR_DATA)
    path = audio_path(avatar_id, speech_id, AVATAR_DATA)
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})


# Production / Raspberry Pi: the built frontend (frontend/dist, `npm run build`) is served by this
# same server, so one process on port 8000 runs everything (no Node/Vite dev server needed).
# Mounted last so every API route above keeps priority.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
