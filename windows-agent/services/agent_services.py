from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

AGENT_ROOT = Path(__file__).resolve().parent.parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", r"C:\Users\parth\AppData\Local\hermes"))
WEBUI_DIR = Path(r"C:\Users\parth\hermes-webui")
GATEWAY_VBS = HERMES_HOME / "gateway-service" / "Hermes_Gateway.vbs"
GATEWAY_STATE = HERMES_HOME / "gateway_state.json"
CINEVAULT_DIR = Path(r"D:\CineVault\server")
THROTTLE_EXES = [
    Path(r"C:\Users\parth\AppData\Local\Programs\Throttle\Throttle.exe"),
    Path(r"D:\Throttle\dist\win-unpacked\Throttle.exe"),
    Path(r"D:\Throttle\dist\portable\win-unpacked\Throttle.exe"),
]

# Background servers the phone can start or stop.
KNOWN_SERVICES = [
    {
        "id": "pc-control",
        "name": "PC Control",
        "description": "This laptop control panel",
        "port": None,
        "logo": "/assets/services/pc-control.svg",
        "confirm_stop": "Stop PC Control? This page will disconnect until you start it on the laptop.",
        "controllable": True,
    },
    {
        "id": "cinevault",
        "name": "CineVault",
        "description": "Media streaming server",
        "port": 8000,
        "logo": "/assets/services/cinevault.png",
        "controllable": True,
    },
    {
        "id": "throttle",
        "name": "Throttle",
        "description": "Model usage dock",
        "port": None,
        "logo": "/assets/services/throttle.png",
        "controllable": True,
    },
    {
        "id": "hermes-gateway",
        "name": "Hermes Gateway",
        "description": "Telegram / Discord agent gateway",
        "port": None,
        "logo": "/assets/services/hermes.png",
        "controllable": True,
    },
    {
        "id": "hermes-webui",
        "name": "Hermes WebUI",
        "description": "Agent web UI",
        "port": 8787,
        "logo": "/assets/services/hermes.png",
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


def _cinevault_port() -> int:
    env_path = CINEVAULT_DIR / ".env"
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "PORT":
                return int(value.strip().strip('"').strip("'") or 8000)
    except (OSError, ValueError):
        pass
    return 8000


def _cinevault_pids(port: int) -> list[int]:
    found: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            lowered = cmdline.lower()
            if "cinevault" in lowered and ("run.py" in lowered or "uvicorn" in lowered or "app.main" in lowered):
                found.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    pid = _listener_pid(port)
    if pid and pid not in found:
        found.append(pid)
    return found


def _throttle_exe() -> Path | None:
    for path in THROTTLE_EXES:
        if path.exists():
            return path
    return None


def _throttle_pids() -> list[int]:
    found: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            exe = (proc.info.get("exe") or "").lower()
            if name == "throttle.exe" or exe.endswith("\\throttle.exe"):
                found.append(int(proc.info["pid"]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _pc_control_python() -> Path:
    return AGENT_ROOT / ".venv" / "Scripts" / "python.exe"


def _spawn(cmd: list[str], cwd: Path) -> None:
    subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=_DETACHED | _NO_WINDOW,
        close_fds=True,
    )


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

    def _spec(self, service_id: str) -> dict:
        for spec in self._resolved_specs():
            if spec["id"] == service_id:
                return spec
        raise ValueError(f"Unknown service '{service_id}'")

    def _resolved_specs(self) -> list[dict]:
        items = []
        for spec in KNOWN_SERVICES:
            item = dict(spec)
            if item["id"] == "pc-control":
                item["port"] = self.agent_port
            elif item["id"] == "cinevault":
                item["port"] = _cinevault_port()
            items.append(item)
        return items

    def list_services(self) -> list[dict]:
        items: list[dict] = []
        for spec in self._resolved_specs():
            port = spec["port"]
            running, pid, extra = self._status(spec["id"], port)
            info: dict = {
                "id": spec["id"],
                "name": spec["name"],
                "description": spec["description"],
                "port": port,
                "logo": spec.get("logo"),
                "confirm_stop": spec.get("confirm_stop"),
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
        if service_id == "pc-control":
            if port is not None and _port_open(port):
                return True, _listener_pid(port) or os.getpid(), {}
            return True, os.getpid(), {"detail": "this panel"}
        if service_id == "cinevault":
            pids = _cinevault_pids(port or _cinevault_port())
            if port is not None and _port_open(port):
                return True, _listener_pid(port) or (pids[0] if pids else None), {}
            if pids:
                return True, pids[0], {"detail": "process alive, port not reachable"}
            return False, None, {}
        if service_id == "throttle":
            pids = _throttle_pids()
            if pids:
                return True, pids[0], {}
            return False, None, {}
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
        spec = self._spec(service_id)
        running, _, _ = self._status(service_id, spec.get("port"))
        if running:
            return {"success": True, "message": f"{spec['name']} is already running"}
        if service_id == "pc-control":
            return self._start_pc_control()
        if service_id == "cinevault":
            return self._start_cinevault(spec.get("port") or _cinevault_port())
        if service_id == "throttle":
            return self._start_throttle()
        if service_id == "hermes-gateway":
            return self._start_gateway()
        if service_id == "hermes-webui":
            return self._start_webui()
        raise ValueError(f"Service '{service_id}' cannot be started")

    def stop(self, service_id: str) -> dict:
        spec = self._spec(service_id)
        if service_id == "pc-control":
            return self._stop_pc_control()
        if service_id == "cinevault":
            pids = _cinevault_pids(spec.get("port") or _cinevault_port())
            if not pids:
                return {"success": True, "message": "CineVault is already stopped"}
            count = _terminate_pids(pids)
            return {"success": True, "message": f"CineVault stopped ({count} process(es))"}
        if service_id == "throttle":
            pids = _throttle_pids()
            if not pids:
                return {"success": True, "message": "Throttle is already stopped"}
            count = _terminate_pids(pids)
            return {"success": True, "message": f"Throttle stopped ({count} process(es))"}
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
        raise ValueError(f"Service '{service_id}' cannot be stopped")

    def toggle(self, service_id: str) -> dict:
        spec = self._spec(service_id)
        running, _, _ = self._status(service_id, spec.get("port"))
        if running:
            return self.stop(service_id)
        return self.start(service_id)

    def _start_pc_control(self) -> dict:
        python = _pc_control_python()
        runner = AGENT_ROOT / "run.py"
        if not python.exists() or not runner.exists():
            raise RuntimeError("PC Control launcher not found")
        _spawn([str(python), str(runner)], AGENT_ROOT)
        return {"success": True, "message": "PC Control start requested"}

    def _stop_pc_control(self) -> dict:
        def halt() -> None:
            time.sleep(0.7)
            os._exit(0)

        threading.Thread(target=halt, daemon=True).start()
        return {"success": True, "message": "PC Control is stopping"}

    def _start_cinevault(self, port: int) -> dict:
        if _port_open(port) or _cinevault_pids(port):
            return {"success": True, "message": "CineVault is already running"}
        if not CINEVAULT_DIR.exists():
            raise RuntimeError(f"CineVault directory not found: {CINEVAULT_DIR}")
        try:
            _spawn(["py", "-3", "run.py"], CINEVAULT_DIR)
        except OSError:
            _spawn(["python.exe", "run.py"], CINEVAULT_DIR)
        return {"success": True, "message": "CineVault start requested"}

    def _start_throttle(self) -> dict:
        if _throttle_pids():
            return {"success": True, "message": "Throttle is already running"}
        exe = _throttle_exe()
        if not exe:
            raise RuntimeError("Throttle.exe was not found")
        _spawn([str(exe)], exe.parent)
        return {"success": True, "message": "Throttle start requested"}

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
