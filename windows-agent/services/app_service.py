from __future__ import annotations

import base64
import ctypes
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

import psutil

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "app_icons"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_WM_CLOSE = 0x0010

# Desktop apps controllable from the phone. `path_hint` disambiguates
# shared process names (Helium runs as chrome.exe).
MANAGED_APPS = [
    {
        "id": "helium",
        "name": "Helium",
        "description": "Browser",
        "exe": r"C:\Users\parth\AppData\Local\imput\Helium\Application\chrome.exe",
        "process_name": "chrome.exe",
        "path_hint": "helium",
    },
    {
        "id": "comet",
        "name": "Comet",
        "description": "Perplexity browser",
        "exe": r"C:\Program Files\Perplexity\Comet\Application\comet.exe",
        "process_name": "comet.exe",
        "path_hint": None,
    },
    {
        "id": "hermes-desktop",
        "name": "Hermes Desktop",
        "description": "Hermes desktop app",
        "exe": r"C:\Users\parth\AppData\Local\hermes\hermes-agent\apps\desktop\release\win-unpacked\Hermes.exe",
        "process_name": "Hermes.exe",
        "path_hint": None,
    },
    {
        "id": "zed",
        "name": "Zed",
        "description": "Code editor",
        "exe": r"C:\Users\parth\AppData\Local\Programs\Zed\Zed.exe",
        "process_name": "zed.exe",
        "path_hint": None,
    },
    {
        "id": "t3code",
        "name": "T3 Code",
        "description": "Nightly editor",
        "exe": r"C:\Users\parth\AppData\Local\Programs\t3code\T3 Code (Nightly).exe",
        "process_name": "T3 Code (Nightly).exe",
        "path_hint": None,
    },
]


def _iter_matching_pids(spec: dict) -> list[int]:
    want = spec["process_name"].lower()
    hint = (spec.get("path_hint") or "").lower()
    found: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
            if (info.get("name") or "").lower() != want:
                continue
            if hint and hint not in (info.get("exe") or "").lower():
                continue
            found.append(int(info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _graceful_close(pids: set[int], timeout: float = 5.0) -> None:
    """Ask visible top-level windows of the PIDs to close (lets apps save state)."""
    try:
        user32 = ctypes.windll.user32
    except (AttributeError, OSError):
        return
    prototype = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _param):
        try:
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if int(pid.value) in pids:
                    user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
        except (OSError, ValueError):
            pass
        return True

    try:
        user32.EnumWindows(prototype(callback), 0)
    except (OSError, ValueError):
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(psutil.pid_exists(pid) for pid in pids):
            return
        time.sleep(0.25)


class AppService:
    def __init__(self) -> None:
        self._logos: dict[str, str | None] = {}

    def logo_data_uri(self, app_id: str) -> str | None:
        if app_id not in self._logos:
            path = ICON_DIR / f"{app_id}.png"
            try:
                raw = path.read_bytes()
                self._logos[app_id] = (
                    "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
                )
            except OSError:
                self._logos[app_id] = None
        return self._logos[app_id]

    def list_apps(self) -> list[dict]:
        items: list[dict] = []
        for spec in MANAGED_APPS:
            pids = _iter_matching_pids(spec)
            items.append(
                {
                    "id": spec["id"],
                    "name": spec["name"],
                    "description": spec["description"],
                    "running": bool(pids),
                    "pid": pids[0] if pids else None,
                    "logo": self.logo_data_uri(spec["id"]),
                }
            )
        return items

    def _spec(self, app_id: str) -> dict:
        for spec in MANAGED_APPS:
            if spec["id"] == app_id:
                return spec
        raise ValueError(f"Unknown app '{app_id}'")

    def start(self, app_id: str) -> dict:
        spec = self._spec(app_id)
        if _iter_matching_pids(spec):
            return {"success": True, "message": f"{spec['name']} is already running"}
        exe = Path(spec["exe"])
        if not exe.exists():
            raise RuntimeError(f"{spec['name']} not found at {exe}")
        subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_DETACHED | _NO_WINDOW,
            close_fds=True,
        )
        return {"success": True, "message": f"{spec['name']} launch requested"}

    def stop(self, app_id: str) -> dict:
        spec = self._spec(app_id)
        pids = _iter_matching_pids(spec)
        if not pids:
            return {"success": True, "message": f"{spec['name']} is already closed"}
        _graceful_close(set(pids))
        remaining = [pid for pid in pids if psutil.pid_exists(pid)]
        for pid in remaining:
            try:
                psutil.Process(pid).terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        _, alive = psutil.wait_procs(
            [psutil.Process(pid) for pid in remaining if psutil.pid_exists(pid)],
            timeout=4.0,
        )
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {"success": True, "message": f"{spec['name']} closed"}

    def toggle(self, app_id: str) -> dict:
        spec = self._spec(app_id)
        if _iter_matching_pids(spec):
            return self.stop(app_id)
        return self.start(app_id)
