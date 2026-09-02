from __future__ import annotations

from fastapi import Header, HTTPException, Request

from security.token_manager import TokenManager


class AuthService:
    def __init__(self, tokens: TokenManager) -> None:
        self.tokens = tokens

    def client_from_header(self, authorization: str | None) -> dict:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        client = self.tokens.authenticate(token)
        if client is None:
            raise HTTPException(status_code=401, detail="Connection rejected. Sign in again with the laptop password.")
        return client


def _hostname(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("["):
        end = raw.find("]")
        if end != -1:
            return raw[1:end]
    return raw.split("/")[0].split(":")[0]


def is_loopback(request: Request) -> bool:
    client = (request.client.host if request.client else "") or ""
    if client not in {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}:
        return False
    forwarded = _hostname(request.headers.get("x-forwarded-host") or "")
    if forwarded and forwarded not in {"127.0.0.1", "localhost", "::1"}:
        return False
    host = _hostname(request.headers.get("host") or "")
    if host and host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    return True


def require_loopback(request: Request) -> None:
    if not is_loopback(request):
        raise HTTPException(status_code=403, detail="Password setup is only available on the laptop")


def bearer_dependency(auth: AuthService):
    def _inner(authorization: str | None = Header(default=None)) -> dict:
        return auth.client_from_header(authorization)

    return _inner
