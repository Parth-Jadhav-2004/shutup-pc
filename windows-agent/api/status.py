from fastapi import APIRouter, Request

from app.context import ctx

router = APIRouter()


@router.get("/status")
def status(request: Request) -> dict:
    ctx.auth.client_from_header(request.headers.get("authorization"))
    return ctx.telemetry.status(ctx.tokens.device_name)
