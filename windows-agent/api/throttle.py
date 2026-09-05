from fastapi import APIRouter, Request

from app.context import ctx

router = APIRouter()


@router.get("/throttle")
def throttle_usage(request: Request, refresh: bool = False) -> dict:
    ctx.auth.client_from_header(request.headers.get("authorization"))
    return ctx.throttle.snapshot(refresh=refresh)
