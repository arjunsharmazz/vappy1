"""Server-Sent Events stream of the viewer's face position (~camera fps). No images leave the server."""
import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..settings import get_settings
from .service import service

router = APIRouter()


@router.get("/vision/status")
def vision_status():
    state, _ = service.snapshot()
    return {**state, "configured": service.enabled}


@router.get("/vision/stream")
async def vision_stream(request: Request):
    async def events():
        if not service.enabled:
            # A distinct flag: the normal state also has "enabled": false for a moment while
            # the camera thread starts, and that must not look like "turned off in settings".
            yield "data: " + json.dumps({"disabled": True}) + "\n\n"
            return
        service.subscribe()
        try:
            seen = -1
            while not await request.is_disconnected():
                state, version = service.snapshot()
                if version != seen:
                    seen = version
                    yield "data: " + json.dumps(state) + "\n\n"
                await asyncio.sleep(1 / 30)
        finally:
            service.unsubscribe()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/vision/video")
async def vision_video(request: Request):
    """Live camera preview as MJPEG (works directly in an <img>). The backend binds to
    127.0.0.1, so the video never leaves this computer. Stops when the panel closes."""
    if not service.enabled or not get_settings()["vision"]["preview"]:
        raise HTTPException(404, "Camera preview is turned off in config/settings.toml ([vision] preview).")

    async def frames():
        service.subscribe(preview=True)
        try:
            seen = -1
            while not await request.is_disconnected():
                jpeg, version = service.latest_jpeg()
                if jpeg and version != seen:
                    seen = version
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode()
                           + b"\r\n\r\n" + jpeg + b"\r\n")
                await asyncio.sleep(1 / 30)
        finally:
            service.unsubscribe(preview=True)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
