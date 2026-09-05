from __future__ import annotations

import os
import socket
from pathlib import Path

from pydantic import BaseModel

_PORT_FILE = Path(__file__).resolve().parent / "agent_port.txt"
_AGENT_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _AGENT_ROOT.parent


def parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env_files(*paths: Path) -> None:
    for path in paths:
        try:
            parsed = parse_env_text(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        for key, value in parsed.items():
            os.environ.setdefault(key, value)


load_env_files(_AGENT_ROOT / ".env", _REPO_ROOT / ".env")


def _agent_port() -> int:
    try:
        return int(_PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 28471


class Settings(BaseModel):
    agent_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = _agent_port()
    data_dir: Path = Path(os.environ.get("LOCALAPPDATA", ".")) / "LaptopRemote"

    @property
    def secrets_path(self) -> Path:
        return self.data_dir / "secrets.bin"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "agent.log"

    @property
    def hostname(self) -> str:
        return socket.gethostname()


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
