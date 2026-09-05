from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from services.throttle.display import normalize_rate_limits

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _extra_path_dirs() -> list[str]:
    home = Path.home()
    local = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
    roaming = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
    return [
        str(Path(roaming) / "npm"),
        str(home / ".local" / "bin"),
        str(Path(local) / "fnm"),
        str(Path(local) / "Programs" / "cursor" / "resources" / "app" / "bin"),
    ]


def find_codex() -> str | None:
    env = os.environ.copy()
    extra = os.pathsep.join(dir_path for dir_path in _extra_path_dirs() if dir_path)
    env["PATH"] = extra + os.pathsep + env.get("PATH", "")
    found = shutil.which("codex", path=env["PATH"])
    if found:
        return found
    if os.name == "nt":
        return shutil.which("codex.cmd", path=env["PATH"]) or shutil.which("codex.exe", path=env["PATH"])
    return None


class CodexClient:
    def __init__(self, command: str | None = None, timeout: float = 20.0) -> None:
        self.command = command or find_codex() or "codex"
        self.timeout = timeout

    def get_rate_limits(self) -> dict:
        argv = [self.command, "app-server", "--stdio"]
        kwargs: dict = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "env": os.environ.copy(),
        }
        extra = os.pathsep.join(_extra_path_dirs())
        kwargs["env"]["PATH"] = extra + os.pathsep + kwargs["env"].get("PATH", "")
        if os.name == "nt":
            kwargs["creationflags"] = _NO_WINDOW
            if str(self.command).lower().endswith((".cmd", ".bat")):
                argv = ["cmd.exe", "/d", "/c", self.command, "app-server", "--stdio"]
        try:
            proc = subprocess.Popen(argv, **kwargs)
        except FileNotFoundError as exc:
            raise RuntimeError("Codex not found. Install the Codex CLI and run `codex login`.") from exc

        next_id = 1
        pending: dict[int, dict] = {}
        done = threading.Event()
        result: dict[str, object] = {"value": None, "error": None}

        def fail(message: str) -> None:
            if result["error"] is None and result["value"] is None:
                result["error"] = RuntimeError(message)
            done.set()

        def send(message: dict) -> None:
            if proc.stdin is None:
                raise RuntimeError("Codex app-server is not running")
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def request(method: str, params: object = None) -> int:
            nonlocal next_id
            ident = next_id
            next_id += 1
            pending[ident] = {"method": method}
            send({"method": method, "id": ident, "params": params})
            return ident

        def handle(message: dict) -> None:
            ident = message.get("id")
            if ident not in pending:
                return
            item = pending.pop(ident)
            if message.get("error"):
                err = message["error"]
                text = err.get("message") if isinstance(err, dict) else str(err)
                fail(text or "Codex request failed")
                return
            if item["method"] == "initialize":
                send({"method": "initialized", "params": {}})
                request("account/rateLimits/read")
                return
            result["value"] = message.get("result") or {}
            done.set()

        def reader() -> None:
            try:
                if proc.stdout is None:
                    fail("Codex app-server produced no output")
                    return
                for line in proc.stdout:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        handle(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if done.is_set():
                        return
                fail(f"Codex app-server exited ({proc.returncode})")
            except Exception as exc:
                fail(str(exc))

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "laptop-remote",
                        "title": "Laptop Remote",
                        "version": "1.0.0",
                    },
                    "capabilities": None,
                },
            )
            if not done.wait(self.timeout):
                raise RuntimeError("account/rateLimits/read timed out")
            if result["error"]:
                raise result["error"]  # type: ignore[misc]
            raw = result["value"]
            if not isinstance(raw, dict):
                raise RuntimeError("Unable to read Codex usage")
            return raw
        finally:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def get_usage(self) -> dict:
        raw = self.get_rate_limits()
        data = normalize_rate_limits(raw)
        if not any(data.get(key) for key in ("fiveHour", "weekly", "monthly")):
            raise RuntimeError("Unable to read Codex usage")
        return data
