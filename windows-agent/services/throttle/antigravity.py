from __future__ import annotations

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from services.throttle.display import normalize_antigravity_usage
from services.throttle.httputil import HttpError, request_json

TOKEN_URL = "https://oauth2.googleapis.com/token"
_CLIENT_ID_RE = re.compile(r"OAUTH_CLIENT_ID\s*=\s*['\"]([^'\"]+)['\"]")
_CLIENT_SECRET_RE = re.compile(r"OAUTH_CLIENT_SECRET\s*=\s*['\"]([^'\"]+)['\"]")
B64_PREFIX = "go-keyring-base64:"
REFRESH_SKEW_MS = 60 * 1000
HOSTS = (
    "daily-cloudcode-pa.googleapis.com",
    "cloudcode-pa.googleapis.com",
)


def decode_credential(raw: str) -> dict:
    text = str(raw or "").strip()
    payload = (
        base64.b64decode(text[len(B64_PREFIX) :]).decode("utf-8")
        if text.startswith(B64_PREFIX)
        else text
    )
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Stored Antigravity credential is not valid JSON") from exc
    token = parsed.get("token") if isinstance(parsed, dict) and isinstance(parsed.get("token"), dict) else parsed
    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str) or not token.get("access_token"):
        raise RuntimeError("Stored Antigravity credential has no access token")
    expiry = token.get("expiry")
    expires_at = None
    if expiry:
        try:
            expires_at = datetime.fromisoformat(str(expiry).replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            expires_at = None
    return {
        "accessToken": token["access_token"],
        "refreshToken": token.get("refresh_token") if isinstance(token.get("refresh_token"), str) else None,
        "expiresAt": expires_at,
    }


def read_windows_credential() -> str | None:
    if os.name != "nt":
        return None
    try:
        import win32cred
    except ImportError:
        return None
    try:
        cred = win32cred.CredRead("gemini:antigravity", win32cred.CRED_TYPE_GENERIC)
    except Exception:
        return None
    blob = cred.get("CredentialBlob") or b""
    if isinstance(blob, str):
        blob = blob.encode("utf-16le")
    utf8 = blob.decode("utf-8", errors="ignore")
    if utf8.startswith(B64_PREFIX) or utf8.lstrip().startswith("{"):
        return utf8
    try:
        return blob.decode("utf-16le")
    except UnicodeDecodeError:
        return utf8 or None


def read_file_credential() -> str | None:
    token_path = Path(
        os.environ.get("AGY_OAUTH_TOKEN_FILE")
        or (Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token")
    )
    try:
        text = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def oauth_client_from_text(text: str) -> tuple[str, str] | None:
    client_id = _CLIENT_ID_RE.search(text)
    client_secret = _CLIENT_SECRET_RE.search(text)
    if not client_id or not client_secret:
        return None
    return client_id.group(1), client_secret.group(1)


def throttle_auth_candidates() -> list[Path]:
    home = os.environ.get("THROTTLE_HOME")
    values = []
    if home:
        values.append(Path(home) / "src" / "antigravity-auth.js")
    values.append(Path(r"D:\throttle") / "src" / "antigravity-auth.js")
    return values


def load_oauth_client() -> tuple[str, str]:
    env_id = os.environ.get("AGY_OAUTH_CLIENT_ID")
    env_secret = os.environ.get("AGY_OAUTH_CLIENT_SECRET")
    if env_id and env_secret:
        return env_id, env_secret
    for path in throttle_auth_candidates():
        try:
            parsed = oauth_client_from_text(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if parsed:
            return parsed
    raise RuntimeError(
        "Antigravity token refresh needs AGY_OAUTH_CLIENT_ID and AGY_OAUTH_CLIENT_SECRET, or a local Throttle checkout."
    )


def refresh_access_token(refresh_token: str) -> str:
    client_id, client_secret = load_oauth_client()
    payload = request_json(
        TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ),
        timeout=15.0,
    )
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise HttpError("Antigravity login required", 401)
    return str(payload["access_token"])


def get_antigravity_access_token() -> str:
    raw = read_windows_credential() or read_file_credential()
    if not raw:
        raise RuntimeError("Antigravity login required")
    credential = decode_credential(raw)
    now_ms = time.time() * 1000
    expiring = (
        isinstance(credential.get("expiresAt"), (int, float))
        and credential["expiresAt"] - now_ms < REFRESH_SKEW_MS
    )
    if expiring and credential.get("refreshToken"):
        return refresh_access_token(credential["refreshToken"])
    return credential["accessToken"]


def fetch_antigravity_snapshot() -> dict:
    access_token = get_antigravity_access_token()
    last_error: Exception | None = None
    for host in HOSTS:
        try:
            payload = request_json(
                f"https://{host}/v1internal:fetchAvailableModels",
                method="POST",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "User-Agent": "antigravity",
                },
                body={},
                timeout=15.0,
            )
        except HttpError as exc:
            last_error = exc
            if exc.status in {401, 403}:
                raise
            continue
        models = payload.get("models") if isinstance(payload, dict) else None
        buckets = []
        if isinstance(models, dict):
            for model in models.values():
                if not isinstance(model, dict) or model.get("isInternal") or not model.get("displayName") or not model.get("quotaInfo"):
                    continue
                quota = model["quotaInfo"]
                try:
                    remaining = float(quota.get("remainingFraction"))
                except (TypeError, ValueError):
                    continue
                buckets.append(
                    {
                        "kind": "model",
                        "label": model.get("displayName"),
                        "remainingFraction": remaining,
                        "resetAt": quota.get("resetTime"),
                        "available": remaining == 1,
                    }
                )
        if not buckets:
            last_error = RuntimeError("Antigravity returned no model quota")
            continue
        return {
            "account": None,
            "tier": None,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "api",
            "host": host,
            "groups": [{"name": "Antigravity models", "models": "", "buckets": buckets}],
        }
    raise last_error or RuntimeError("Unable to read Antigravity usage")


class AntigravityClient:
    def __init__(self, cache_ms: int = 5 * 60 * 1000) -> None:
        self.cache_ms = cache_ms
        self.cached: dict[str, Any] | None = None

    def get_usage(self, bypass_cache: bool = False) -> dict:
        now = time.time() * 1000
        if not bypass_cache and self.cached and now - self.cached["at"] < self.cache_ms:
            return self.cached["data"]
        snapshot = fetch_antigravity_snapshot()
        data = normalize_antigravity_usage(snapshot)
        if data.get("usedPercent") is None:
            raise RuntimeError("Unable to read Antigravity usage")
        self.cached = {"at": now, "data": data}
        return data
