from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable

from services.throttle.antigravity import AntigravityClient
from services.throttle.claude import ClaudeClient
from services.throttle.codex import CodexClient
from services.throttle.cursor import CursorClient
from services.throttle.display import limits_for_provider, needs_login, used_percent_for_provider

PROVIDERS = (
    {"id": "claude", "name": "Claude"},
    {"id": "cursor", "name": "Cursor"},
    {"id": "codex", "name": "Codex"},
    {"id": "antigravity", "name": "Antigravity"},
)
CACHE_MS = 45_000


class ThrottleService:
    def __init__(self) -> None:
        self._cursor = CursorClient()
        self._claude = ClaudeClient()
        self._codex = CodexClient()
        self._antigravity = AntigravityClient()
        self._cache: dict[str, dict[str, Any]] = {}

    def snapshot(self, refresh: bool = False) -> dict:
        now = time.time() * 1000
        jobs: dict[str, Callable[[], dict]] = {
            "claude": self._claude.get_usage,
            "cursor": self._cursor.get_usage,
            "codex": self._codex.get_usage,
            "antigravity": lambda: self._antigravity.get_usage(bypass_cache=refresh),
        }
        results: dict[str, dict[str, Any]] = {}
        to_fetch: dict[str, Callable[[], dict]] = {}
        for provider_id, loader in jobs.items():
            cached = self._cache.get(provider_id)
            if not refresh and cached and now - cached["updated_at"] < CACHE_MS:
                results[provider_id] = cached
            else:
                to_fetch[provider_id] = loader

        if to_fetch:
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(self._load, provider_id, loader): provider_id for provider_id, loader in to_fetch.items()}
                for future in as_completed(futures):
                    provider_id = futures[future]
                    state = future.result()
                    self._cache[provider_id] = state
                    results[provider_id] = state

        providers = []
        for spec in PROVIDERS:
            state = results.get(spec["id"]) or self._cache.get(spec["id"]) or {
                "status": "error",
                "error": "Usage is not ready yet",
                "data": None,
                "updated_at": now,
            }
            providers.append(self._view(spec, state))
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "providers": providers,
        }

    def _load(self, provider_id: str, loader: Callable[[], dict]) -> dict:
        updated_at = time.time() * 1000
        try:
            data = loader()
            return {"status": "connected", "data": data, "error": None, "updated_at": updated_at}
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            return {
                "status": "disconnected" if needs_login(message) else "error",
                "data": None,
                "error": message,
                "updated_at": updated_at,
            }

    def _view(self, spec: dict[str, str], state: dict[str, Any]) -> dict[str, Any]:
        data = state.get("data") if state.get("status") == "connected" else None
        used = used_percent_for_provider(spec["id"], data)
        remaining_label = data.get("remainingLabel") if isinstance(data, dict) else None
        plan_type = data.get("planType") if isinstance(data, dict) else None
        updated_at = state.get("updated_at")
        captured = None
        if isinstance(updated_at, (int, float)):
            captured = datetime.fromtimestamp(updated_at / 1000.0, tz=timezone.utc).isoformat()
        return {
            "id": spec["id"],
            "name": spec["name"],
            "status": state.get("status") or "error",
            "plan_type": plan_type,
            "used_percent": used,
            "remaining_label": remaining_label,
            "error": state.get("error"),
            "updated_at": captured,
            "limits": limits_for_provider(spec["id"], data),
        }
