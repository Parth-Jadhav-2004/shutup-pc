from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any = None,
    timeout: float = 15.0,
) -> Any:
    payload: bytes | None = None
    req_headers = dict(headers or {})
    req_headers.setdefault("User-Agent", "LaptopRemote/1.0")
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
        elif isinstance(body, str):
            payload = body.encode("utf-8")
        else:
            payload = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
        parsed = _parse_json(text)
        message = _error_message(parsed) or f"Request failed ({status})"
        raise HttpError(message, status) from None
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc) or exc)
        if "timed out" in reason.lower():
            raise HttpError("Request timed out") from None
        raise HttpError(reason) from None
    except TimeoutError as exc:
        raise HttpError("Request timed out") from exc

    parsed = _parse_json(text)
    if status >= 400:
        raise HttpError(_error_message(parsed) or f"Request failed ({status})", status)
    return parsed


def _parse_json(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code")
        if message:
            return str(message)
    if isinstance(error, str) and error:
        return error
    if payload.get("message"):
        return str(payload["message"])
    if payload.get("error_description"):
        return str(payload["error_description"])
    return None
