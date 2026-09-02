from __future__ import annotations

import time
from collections import defaultdict


class LoginGuard:
    def __init__(self, max_failures: int = 8, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = defaultdict(list)

    def allow(self, client_ip: str) -> bool:
        self._prune(client_ip)
        return len(self._failures[client_ip]) < self.max_failures

    def record_failure(self, client_ip: str) -> None:
        self._failures[client_ip].append(time.time())
        self._prune(client_ip)

    def reset(self, client_ip: str) -> None:
        self._failures.pop(client_ip, None)

    def _prune(self, client_ip: str) -> None:
        cutoff = time.time() - self.window_seconds
        self._failures[client_ip] = [stamp for stamp in self._failures[client_ip] if stamp >= cutoff]
