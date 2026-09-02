from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.context import ctx
from config.settings import settings
from services.auth_service import require_loopback
from services.login_guard import LoginGuard

router = APIRouter()
logger = logging.getLogger("laptop_remote")
guard = LoginGuard()


class LoginRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)
    client_name: str = Field(default="Web", max_length=64)


class PasswordRequest(BaseModel):
    password: str = Field(min_length=6, max_length=128)


def _urls() -> tuple[str, str | None]:
    local_ip = ctx.network.local_ip()
    return ctx.network.base_url(local_ip, settings.port), ctx.network.remote_url(settings.port)


@router.get("/auth/status")
def auth_status() -> dict:
    return {
        "password_set": ctx.tokens.has_password(),
        "device_name": ctx.tokens.device_name,
        "device_id": ctx.tokens.device_id,
        "local_url": _urls()[0],
        "remote_url": _urls()[1],
    }


@router.post("/auth/login")
def login(request: Request, body: LoginRequest) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    if not guard.allow(client_ip):
        logger.warning("login_throttled client=%s", client_ip)
        raise HTTPException(status_code=429, detail="Too many failed logins. Wait a few minutes and try again.")
    if not ctx.tokens.verify_password(body.password):
        guard.record_failure(client_ip)
        logger.warning("login_rejected client=%s", client_ip)
        raise HTTPException(status_code=401, detail="Incorrect password.")

    guard.reset(client_ip)
    client_id, device_token = ctx.tokens.add_client(body.client_name)
    local_url, remote_url = _urls()
    logger.info("login_succeeded client=%s client_id=%s", client_ip, client_id)
    return {
        "success": True,
        "client_id": client_id,
        "device_id": ctx.tokens.device_id,
        "device_name": ctx.tokens.device_name,
        "device_token": device_token,
        "local_url": local_url,
        "remote_url": remote_url,
    }


@router.post("/auth/password")
def set_password(request: Request, body: PasswordRequest) -> dict:
    require_loopback(request)
    try:
        ctx.tokens.set_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    logger.info("password_updated")
    return {"success": True, "message": "Password updated"}
