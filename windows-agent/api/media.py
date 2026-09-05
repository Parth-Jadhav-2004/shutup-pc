from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.context import ctx

router = APIRouter()


class VolumeRequest(BaseModel):
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    muted: bool | None = None


def _require(request: Request) -> None:
    ctx.auth.client_from_header(request.headers.get("authorization"))


@router.get("/media/screenshot")
def screenshot(request: Request) -> Response:
    _require(request)
    try:
        payload = ctx.media.screenshot_jpeg()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {exc}") from exc
    return Response(content=payload, media_type="image/jpeg")


@router.get("/media/volume")
def get_volume(request: Request) -> dict:
    _require(request)
    try:
        return ctx.media.volume()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Volume is unavailable: {exc}") from exc


@router.post("/media/volume")
def set_volume(request: Request, body: VolumeRequest) -> dict:
    _require(request)
    if body.volume_percent is None and body.muted is None:
        raise HTTPException(status_code=400, detail="Set volume_percent or muted.")
    try:
        return ctx.media.set_volume(body.volume_percent, body.muted)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Volume could not be changed: {exc}") from exc
