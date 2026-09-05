from __future__ import annotations

import json
import os
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil

HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\Users\parth\AppData\Local\hermes"))
WEBUI_DIR = Path(r"C:\Users\parth\hermes-webui")
GATEWAY_VBS = HERMES_HOME / "gateway-service" / "Hermes_Gateway.vbs"
GATEWAY_STATE = HERMES_HOME / "gateway_state.json"

# Services the panel knows about. Both are controllable from the phone.
KNOWN_SERVICES = [
    {
        "id": "hermes-gateway",
        "name": "Hermes Gateway",
        "description": "Telegram / Discord agent gateway",
        "port": None,
        "controllable": True,
    },
    {
        "id": "hermes-webui",
        "name": "Hermes WebUI",
        "description": "Agent web UI (:8787)",
        "port": 8787,
        "controllable": True,
    },
]

_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _port_open(port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _listener_pid(port: int) -> int | None:
    try:
        for conn in psutil.net_connections(kind="inet"):
            try:
                laddr = conn.laddr
                cport = laddr.port if hasattr(laddr, "port") else laddr[1]
                if int(cport) == port and conn.status == "LISTEN" and conn.pid:
                    return int(conn.pid)
            except (ValueError, IndexError, AttributeError):
                continue
    except (psutil.AccessDenied, psutil.Error):
        pass
    return None


def _proc_info(pid: int) -> dict:
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = proc.name()
            cmdline = " ".join(proc.cmdline())
        return {"pid": pid, "process_name": name, "cmdline": cmdline[:300]}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return {"pid": pid, "process_name": None, "cmdline": None}


def _gateway_pids() -> list[int]:
    found: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "gateway" in cmdline and "run" in cmdline and "hermes" in cmdline.lower():
                found.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _webui_pids() -> list[int]:
    found: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if "server.py" in cmdline and "hermes-webui" in cmdline:
                found.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    pid = _listener_pid(8787)
    if pid and pid not in found:
        found.append(pid)
    return found


def _terminate_pids(pids: list[int], timeout: float = 6.0) -> int:
    stopped = 0
    procs: list[psutil.Process] = []
    for pid in pids:
        try:
            procs.append(psutil.Process(pid))
        except psutil.NoSuchProcess:
            stopped += 1
    for proc in procs:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, still_alive = psutil.wait_procs(alive, timeout=3.0)
    stopped += len(procs) - len(still_alive)
    return stopped


@dataclass
class AgentServices:
    agent_port: int = 28471

    def list_services(self) -> list[dict]:
        items: list[dict] = []
        for spec in KNOWN_SERVICES:
            port = spec["port"]
            running, pid, extra = self._status(spec["id"], port)
            info: dict = {
                "id": spec["id"],
                "name": spec["name"],
                "description": spec["description"],
                "port": port,
                "controllable": spec["controllable"],
                "running": running,
                "pid": pid,
            }
            info.update(extra)
            if pid:
                info.update(_proc_info(pid))
            items.append(info)
        return items

    def _status(self, service_id: str, port: int | None) -> tuple[bool, int | None, dict]:
        if service_id == "hermes-gateway":
            pids = _gateway_pids()
            if pids:
                return True, pids[0], {"detail": "gateway process running"}
            state = self._gateway_state()
            return False, None, {"detail": state}
        if service_id == "hermes-webui":
            if port is not None and _port_open(port):
                return True, _listener_pid(port), {}
            pids = _webui_pids()
            if pids:
                return True, pids[0], {"detail": "process alive, port not reachable"}
            return False, None, {}
        if port is not None:
            if _port_open(port):
                return True, _listener_pid(port), {}
            return False, None, {}
        return False, None, {}

    def _gateway_state(self) -> str:
        try:
            state = json.loads(GATEWAY_STATE.read_text(encoding="utf-8"))
            pid = state.get("pid")
            if pid and psutil.pid_exists(int(pid)):
                return f"last state: {state.get('gateway_state', 'unknown')}"
            return "stopped"
        except (OSError, ValueError):
            return "stopped"

    def start(self, service_id: str) -> dict:
        if service_id == "hermes-gateway":
            return self._start_gateway()
        if service_id == "hermes-webui":
            return self._start_webui()
        raise ValueError(f"Service '{service_id}' is read-only and cannot be started")

    def stop(self, service_id: str) -> dict:
        if service_id == "hermes-gateway":
            pids = _gateway_pids()
            if not pids:
                return {"success": True, "message": "Hermes Gateway is already stopped"}
            count = _terminate_pids(pids)
            return {"success": True, "message": f"Hermes Gateway stopped ({count} process(es))"}
        if service_id == "hermes-webui":
            pids = _webui_pids()
            if not pids:
                return {"success": True, "message": "Hermes WebUI is already stopped"}
            count = _terminate_pids(pids)
            return {"success": True, "message": f"Hermes WebUI stopped ({count} process(es))"}
        raise ValueError(f"Service '{service_id}' is read-only and cannot be stopped")

    def toggle(self, service_id: str) -> dict:
        running, _, _ = self._status(
            service_id,
            8787 if service_id == "hermes-webui" else None,
        )
        if running:
            return self.stop(service_id)
        return self.start(service_id)

    def _start_gateway(self) -> dict:
        if _gateway_pids():
            return {"success": True, "message": "Hermes Gateway is already running"}
        # Preferred: the registered Hermes_Gateway scheduled task.
        try:
            result = subprocess.run(
                ["schtasks", "/run", "/tn", "Hermes_Gateway"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                creationflags=_NO_WINDOW,
            )
            if result.returncode == 0:
                return {"success": True, "message": "Hermes Gateway start requested"}
        except (OSError, subprocess.SubprocessError):
            pass
        if GATEWAY_VBS.exists():
            subprocess.Popen(
                ["wscript.exe", str(GATEWAY_VBS)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=_DETACHED | _NO_WINDOW,
                close_fds=True,
            )
            return {"success": True, "message": "Hermes Gateway start requested"}
        venv_python = HERMES_HOME / "hermes-agent" / "venv" / "Scripts" / "python.exe"
        if not venv_python.exists():
            raise RuntimeError("Gateway launcher not found (no VBS and no venv python)")
        subprocess.Popen(
            [str(venv_python), "-m", "hermes_cli.main", "gateway", "run"],
            cwd=str(HERMES_HOME),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_DETACHED | _NO_WINDOW,
            close_fds=True,
        )
        return {"success": True, "message": "Hermes Gateway start requested"}

    def _start_webui(self) -> dict:
        if _port_open(8787) or _webui_pids():
            return {"success": True, "message": "Hermes WebUI is already running"}
        start_ps1 = WEBUI_DIR / "start.ps1"
        if not WEBUI_DIR.exists():
            raise RuntimeError(f"WebUI directory not found: {WEBUI_DIR}")
        if start_ps1.exists():
            cmd = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(start_ps1),
            ]
        else:
            cmd = ["python.exe", "server.py"]
        subprocess.Popen(
            cmd,
            cwd=str(WEBUI_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=_DETACHED | _NO_WINDOW,
            close_fds=True,
        )
        return {"success": True, "message": "Hermes WebUI start requested"}
