from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from services.throttle.display import normalize_antigravity_usage, pretty_antigravity_label
from services.throttle.httputil import HttpError, request_json

TOKEN_URL = "https://oauth2.googleapis.com/token"
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


def load_oauth_client() -> tuple[str, str]:
    from config.settings import settings as _settings  # loads windows-agent/.env

    _ = _settings
    client_id = os.environ.get("AGY_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("AGY_OAUTH_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret
    raise RuntimeError(
        "Set AGY_OAUTH_CLIENT_ID and AGY_OAUTH_CLIENT_SECRET in windows-agent/.env"
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


def _iter_models(models: Any):
    if isinstance(models, dict):
        yield from models.items()
    elif isinstance(models, list):
        for model in models:
            if not isinstance(model, dict):
                continue
            model_id = model.get("id") or model.get("name") or model.get("modelId") or ""
            yield str(model_id), model


def _quota_remaining(quota: Any) -> float | None:
    if not isinstance(quota, dict):
        return None
    for key in ("remainingFraction", "remaining_fraction"):
        try:
            return float(quota[key])
        except (TypeError, ValueError, KeyError):
            continue
    remaining = quota.get("remaining")
    if isinstance(remaining, dict):
        for key in ("remainingFraction", "remaining_fraction", "value"):
            try:
                return float(remaining[key])
            except (TypeError, ValueError, KeyError):
                continue
    return None


def buckets_from_models(models: Any) -> list[dict]:
    buckets = []
    for model_id, model in _iter_models(models):
        if not isinstance(model, dict) or model.get("isInternal"):
            continue
        if str(model_id).startswith(("tab_", "chat_")):
            continue
        quota = model.get("quotaInfo")
        if not isinstance(quota, dict):
            continue
        remaining = _quota_remaining(quota)
        if remaining is None:
            remaining = 0.0
        remaining = min(1.0, max(0.0, remaining))
        buckets.append(
            {
                "kind": "model",
                "label": pretty_antigravity_label(model_id, model.get("displayName")),
                "modelId": model_id,
                "remainingFraction": remaining,
                "resetAt": quota.get("resetTime") or quota.get("resetAt"),
                "available": remaining == 1,
            }
        )
    return buckets


def preferred_flash_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    tiered = payload.get("tieredModelIds")
    if not isinstance(tiered, dict):
        return []
    flash = tiered.get("flash")
    if isinstance(flash, str) and flash:
        return [flash]
    if isinstance(flash, list):
        return [str(item) for item in flash if item]
    return []


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
        buckets = buckets_from_models(models)
        if not buckets:
            last_error = RuntimeError("Antigravity returned no model quota")
            continue
        return {
            "account": None,
            "tier": None,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "api",
            "host": host,
            "preferredFlashIds": preferred_flash_ids(payload),
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
