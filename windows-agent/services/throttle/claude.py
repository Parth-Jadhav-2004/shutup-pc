from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from services.throttle.display import normalize_claude_usage
from services.throttle.httputil import HttpError, request_json

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URLS = (
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
)
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
USER_AGENT = "claude-code/2.1.201"
REFRESH_SKEW_MS = 5 * 60 * 1000


def claude_credentials_path() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(config_dir) / ".credentials.json"


def legacy_claude_credentials_path() -> Path:
    return Path.home() / ".claude.json"


def oauth_from_payload(payload: Any) -> dict | None:
    block = payload.get("claudeAiOauth") if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        block = payload if isinstance(payload, dict) else {}
    access_token = block.get("accessToken") if isinstance(block.get("accessToken"), str) else None
    refresh_token = block.get("refreshToken") if isinstance(block.get("refreshToken"), str) else None
    if not access_token and not refresh_token:
        return None
    expires_at = block.get("expiresAt")
    try:
        expires_at_n = float(expires_at)
    except (TypeError, ValueError):
        expires_at_n = None
    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": expires_at_n,
        "subscriptionType": block.get("subscriptionType"),
        "rateLimitTier": block.get("rateLimitTier"),
    }


def read_claude_auth() -> dict:
    for file_path in (claude_credentials_path(), legacy_claude_credentials_path()):
        try:
            auth = oauth_from_payload(json.loads(file_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if auth:
            auth["credentialsPath"] = str(file_path)
            return auth
    raise RuntimeError("Claude login required")


def merge_refreshed_oauth(existing: Any, tokens: dict, now_ms: float) -> dict:
    next_block = {
        "accessToken": tokens["accessToken"],
        "refreshToken": tokens.get("refreshToken")
        or (existing.get("claudeAiOauth") or {}).get("refreshToken")
        or existing.get("refreshToken"),
        "expiresAt": tokens.get("expiresAt")
        if tokens.get("expiresAt") is not None
        else now_ms + float(tokens.get("expiresIn") or 3600) * 1000,
        "subscriptionType": (existing.get("claudeAiOauth") or {}).get("subscriptionType")
        or existing.get("subscriptionType"),
        "rateLimitTier": (existing.get("claudeAiOauth") or {}).get("rateLimitTier") or existing.get("rateLimitTier"),
    }
    if isinstance(existing, dict) and isinstance(existing.get("claudeAiOauth"), dict):
        merged = dict(existing)
        oauth = dict(existing["claudeAiOauth"])
        oauth.update(next_block)
        merged["claudeAiOauth"] = oauth
        return merged
    return {"claudeAiOauth": next_block}


def is_auth_error(error: Exception) -> bool:
    status = getattr(error, "status", None)
    if status in {401, 403}:
        return True
    return bool(re.search(r"unauthorized|unauthenticated|login", str(error), re.I))


class ClaudeClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def usage_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": USER_AGENT,
            "anthropic-version": "2023-06-01",
        }

    def is_expiring(self, auth: dict, now_ms: float | None = None) -> bool:
        now = now_ms if now_ms is not None else time.time() * 1000
        expires_at = auth.get("expiresAt")
        return expires_at is not None and float(expires_at) - now <= REFRESH_SKEW_MS

    def refresh_access_token(self, refresh_token: str) -> dict:
        last_error: Exception | None = None
        for url in TOKEN_URLS:
            try:
                payload = request_json(
                    url,
                    method="POST",
                    headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
                    body={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": CLIENT_ID,
                    },
                    timeout=self.timeout,
                )
            except HttpError as exc:
                last_error = exc
                if exc.status not in {404, 405}:
                    raise
                continue
            if not isinstance(payload, dict) or not payload.get("access_token"):
                raise HttpError("Claude login required", 401)
            return {
                "accessToken": payload["access_token"],
                "refreshToken": payload.get("refresh_token") or refresh_token,
                "expiresIn": payload.get("expires_in"),
            }
        raise last_error or HttpError("Claude login required", 401)

    def persist_tokens(self, auth: dict, tokens: dict) -> None:
        credentials_path = auth.get("credentialsPath")
        if not credentials_path:
            return
        path = Path(credentials_path)
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {"claudeAiOauth": {}}
        next_payload = merge_refreshed_oauth(existing, tokens, time.time() * 1000)
        path.write_text(json.dumps(next_payload, indent=2) + "\n", encoding="utf-8")

    def resolve_token(self, auth: dict) -> tuple[str, dict]:
        if auth.get("accessToken") and not self.is_expiring(auth):
            return auth["accessToken"], auth
        if not auth.get("refreshToken"):
            raise HttpError("Claude login required", 401)
        tokens = self.refresh_access_token(auth["refreshToken"])
        self.persist_tokens(auth, tokens)
        updated = dict(auth)
        updated["accessToken"] = tokens["accessToken"]
        updated["refreshToken"] = tokens["refreshToken"]
        updated["expiresAt"] = time.time() * 1000 + float(tokens.get("expiresIn") or 3600) * 1000
        return tokens["accessToken"], updated

    def load_usage(self, token: str, auth: dict) -> dict:
        payload = request_json(USAGE_URL, headers=self.usage_headers(token), timeout=self.timeout)
        data = normalize_claude_usage(payload, auth)
        if not data.get("fiveHour") and not data.get("weekly"):
            raise RuntimeError("Unable to read Claude usage")
        return data

    def get_usage(self) -> dict:
        auth = read_claude_auth()
        token, resolved = self.resolve_token(auth)
        try:
            return self.load_usage(token, resolved)
        except Exception as exc:
            if not is_auth_error(exc) or not resolved.get("refreshToken"):
                raise
            tokens = self.refresh_access_token(resolved["refreshToken"])
            self.persist_tokens(resolved, tokens)
            merged = dict(resolved)
            merged.update(tokens)
            return self.load_usage(tokens["accessToken"], merged)
