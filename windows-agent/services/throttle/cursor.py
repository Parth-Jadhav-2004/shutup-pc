from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from services.throttle.display import normalize_cursor_usage
from services.throttle.httputil import HttpError, request_json

DEFAULT_BASE_URL = "https://api2.cursor.sh"
OAUTH_CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"
REFRESH_SKEW_MS = 5 * 60 * 1000
AUTH_KEYS = {
    "accessToken": "cursorAuth/accessToken",
    "refreshToken": "cursorAuth/refreshToken",
    "membershipType": "cursorAuth/stripeMembershipType",
}
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
MEMBERSHIP_RE = re.compile(r"\b(free|hobby|pro|plus|ultra|team|business|enterprise|pro_plus)\b", re.I)


def cursor_state_db_path() -> Path:
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / "Cursor" / "User" / "globalStorage" / "state.vscdb"


def jwt_expiry_ms(token: str | None) -> int | None:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        import base64

        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None
    exp = data.get("exp")
    try:
        return int(float(exp) * 1000)
    except (TypeError, ValueError):
        return None


def is_expiring(token: str | None, now_ms: float, skew_ms: int = REFRESH_SKEW_MS) -> bool:
    expiry = jwt_expiry_ms(token)
    return expiry is not None and expiry - now_ms <= skew_ms


def is_auth_error(error: Exception) -> bool:
    status = getattr(error, "status", None)
    if status in {401, 403}:
        return True
    return bool(re.search(r"unauthorized|unauthenticated|login", str(error), re.I))


def _text_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace").strip()
        return text or None
    text = str(value).strip()
    return text or None


def _extract_after_key(buffer: bytes, key: str, pattern: re.Pattern[str], limit: int = 8192) -> str | None:
    key_bytes = key.encode("utf-8")
    found = None
    index = 0
    while True:
        index = buffer.find(key_bytes, index)
        if index < 0:
            break
        slice_bytes = buffer[index + len(key_bytes) : index + len(key_bytes) + limit]
        match = pattern.search(slice_bytes.decode("latin1", errors="ignore"))
        if match:
            found = match.group(0)
        index += len(key_bytes)
    return found


def _auth_from_buffer(buffer: bytes) -> dict[str, str | None]:
    membership = _extract_after_key(buffer, AUTH_KEYS["membershipType"], MEMBERSHIP_RE, 96)
    return {
        "accessToken": _extract_after_key(buffer, AUTH_KEYS["accessToken"], JWT_RE),
        "refreshToken": _extract_after_key(buffer, AUTH_KEYS["refreshToken"], JWT_RE),
        "membershipType": membership.lower() if membership else None,
    }


def _merge_auth(base: dict[str, str | None], nxt: dict[str, str | None]) -> dict[str, str | None]:
    return {
        "accessToken": nxt.get("accessToken") or base.get("accessToken"),
        "refreshToken": nxt.get("refreshToken") or base.get("refreshToken"),
        "membershipType": nxt.get("membershipType") or base.get("membershipType"),
    }


def _query_cursor_auth(db_path: Path) -> dict[str, str | None]:
    with tempfile.TemporaryDirectory(prefix="laptop-remote-cursor-") as tmp:
        tmp_db = Path(tmp) / "state.vscdb"
        tmp_db.write_bytes(db_path.read_bytes())
        for suffix in ("-wal", "-shm"):
            extra = Path(str(db_path) + suffix)
            if extra.exists():
                try:
                    Path(str(tmp_db) + suffix).write_bytes(extra.read_bytes())
                except OSError:
                    pass
        conn = sqlite3.connect(f"{tmp_db.as_uri()}?mode=ro", uri=True)
        try:
            def read(key: str) -> str | None:
                row = conn.execute("SELECT value FROM ItemTable WHERE key = ? LIMIT 1", (key,)).fetchone()
                return _text_value(row[0] if row else None)

            return {
                "accessToken": read(AUTH_KEYS["accessToken"]),
                "refreshToken": read(AUTH_KEYS["refreshToken"]),
                "membershipType": read(AUTH_KEYS["membershipType"]),
            }
        finally:
            conn.close()


def read_cursor_auth(db_path: Path | None = None) -> dict[str, str | None]:
    path = db_path or cursor_state_db_path()
    if not path.exists():
        raise RuntimeError("Cursor is not installed or has not been signed in on this computer.")
    auth: dict[str, str | None] = {"accessToken": None, "refreshToken": None, "membershipType": None}
    try:
        auth = _merge_auth(auth, _query_cursor_auth(path))
    except Exception:
        pass
    for candidate in (path, Path(str(path) + "-wal")):
        try:
            buffer = candidate.read_bytes()
        except OSError:
            continue
        if buffer:
            auth = _merge_auth(auth, _auth_from_buffer(buffer))
    if not auth.get("accessToken") and not auth.get("refreshToken"):
        raise RuntimeError("Cursor login required")
    return auth


class CursorClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.base_url = DEFAULT_BASE_URL.rstrip("/")

    def _payload(self, payload: Any) -> Any:
        if isinstance(payload, dict) and payload.get("error"):
            error = payload["error"]
            if isinstance(error, dict):
                message = error.get("message") or error.get("code") or "Cursor request failed"
                status = 401 if re.search(r"unauth", str(error.get("code") or ""), re.I) else 400
            else:
                message = str(error)
                status = 400
            raise HttpError(message, status)
        return payload

    def dashboard(self, method: str, token: str) -> Any:
        return self._payload(request_json(
            f"{self.base_url}/aiserver.v1.DashboardService/{method}",
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
            },
            body={},
            timeout=self.timeout,
        ))

    def request_usage(self, token: str) -> Any:
        return self._payload(request_json(
            f"{self.base_url}/auth/usage",
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
        ))

    def refresh_access_token(self, refresh_token: str) -> str:
        payload = self._payload(request_json(
            f"{self.base_url}/oauth/token",
            method="POST",
            body={
                "grant_type": "refresh_token",
                "client_id": OAUTH_CLIENT_ID,
                "refresh_token": refresh_token,
            },
            timeout=self.timeout,
        ))
        if not isinstance(payload, dict) or payload.get("shouldLogout") or not payload.get("access_token"):
            error = HttpError("Cursor login required", 401)
            raise error
        return str(payload["access_token"])

    def resolve_token(self, auth: dict[str, str | None], now_ms: float | None = None) -> str:
        import time

        now = now_ms if now_ms is not None else time.time() * 1000
        token = auth.get("accessToken")
        if not token or is_expiring(token, now):
            if not auth.get("refreshToken"):
                raise HttpError("Cursor login required", 401)
            token = self.refresh_access_token(auth["refreshToken"])
        return token

    def load_usage(self, token: str, membership_type: str | None) -> dict:
        usage = None
        plan_info = None
        request_usage = None
        try:
            usage = self.dashboard("GetCurrentPeriodUsage", token)
        except Exception as exc:
            if is_auth_error(exc):
                raise
        try:
            plan_info = self.dashboard("GetPlanInfo", token)
        except Exception as exc:
            if is_auth_error(exc):
                raise
        if not (isinstance(usage, dict) and usage.get("planUsage")):
            try:
                request_usage = self.request_usage(token)
            except Exception as exc:
                if is_auth_error(exc):
                    raise
                if usage is None:
                    raise
        data = normalize_cursor_usage(usage, plan_info, membership_type, request_usage)
        if not data.get("included") and not data.get("api"):
            raise RuntimeError("Unable to read Cursor usage")
        return data

    def get_usage(self) -> dict:
        auth = read_cursor_auth()
        token = self.resolve_token(auth)
        try:
            return self.load_usage(token, auth.get("membershipType"))
        except Exception as exc:
            if not is_auth_error(exc) or not auth.get("refreshToken"):
                raise
            token = self.refresh_access_token(auth["refreshToken"])
            return self.load_usage(token, auth.get("membershipType"))
