from __future__ import annotations

import os
import socket
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    agent_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8765
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
