from fastapi import APIRouter, Header, Request

from app.context import ctx
from config.settings import settings

router = APIRouter()


@router.get("/health")
def health(authorization: str | None = Header(default=None)) -> dict:
    authenticated = False
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        authenticated = ctx.tokens.authenticate(token) is not None
    return ctx.telemetry.health(ctx.tokens.device_id, authenticated)


@router.get("/diagnostics")
def diagnostics(request: Request) -> dict:
    ctx.auth.client_from_header(request.headers.get("authorization"))
    return ctx.network.diagnostics(
        port=settings.port,
        sessions=len(ctx.tokens.paired_clients()),
        extra={
            "device_id": ctx.tokens.device_id,
            "device_name": ctx.tokens.device_name,
            "agent_version": settings.agent_version,
            "hostname": settings.hostname,
        },
    )
