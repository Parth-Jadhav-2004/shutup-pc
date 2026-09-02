from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import win32crypt


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        200_000,
    ).hex()


def secrets_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


class TokenManager:
    """Persist login and device secrets with Windows DPAPI."""

    def __init__(self, path: Path, default_name: str) -> None:
        self.path = path
        self.default_name = default_name
        self._generated_password: str | None = None
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = {
                "device_id": str(uuid.uuid4()),
                "device_name": self.default_name,
                "paired_clients": [],
                "password_hash": None,
                "password_salt": None,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._write(data)
            return data

        encrypted = self.path.read_bytes()
        try:
            decrypted = win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1]
            return json.loads(decrypted.decode("utf-8"))
        except Exception:
            data = {
                "device_id": str(uuid.uuid4()),
                "device_name": self.default_name,
                "paired_clients": [],
                "password_hash": None,
                "password_salt": None,
            }
            self._write(data)
            return data

    def _write(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        encrypted = win32crypt.CryptProtectData(payload, "LaptopRemote", None, None, None, 0)
        self.path.write_bytes(encrypted)

    def save(self) -> None:
        self._write(self._data)

    @property
    def device_id(self) -> str:
        return str(self._data["device_id"])

    @property
    def device_name(self) -> str:
        return str(self._data.get("device_name") or self.default_name)

    def rename_device(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Device name cannot be empty")
        self._data["device_name"] = cleaned[:64]
        self.save()

    def paired_clients(self) -> list[dict[str, Any]]:
        return list(self._data.get("paired_clients") or [])

    def add_client(self, client_name: str) -> tuple[str, str]:
        client_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        clients = self.paired_clients()
        clients.append(
            {
                "client_id": client_id,
                "client_name": (client_name or "Web")[:64],
                "token_hash": hash_secret(token),
                "created_at": _utcnow(),
            }
        )
        self._data["paired_clients"] = clients
        self.save()
        return client_id, token

    def remove_client(self, client_id: str) -> bool:
        clients = self.paired_clients()
        remaining = [item for item in clients if item.get("client_id") != client_id]
        if len(remaining) == len(clients):
            return False
        self._data["paired_clients"] = remaining
        self.save()
        return True

    def authenticate(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        digest = hash_secret(token)
        for client in self.paired_clients():
            stored = str(client.get("token_hash") or "")
            if stored and secrets_equal(stored, digest):
                return client
        return None

    def has_password(self) -> bool:
        return bool(self._data.get("password_hash") and self._data.get("password_salt"))

    def ensure_password(self) -> str | None:
        if self.has_password():
            return None
        password = secrets.token_urlsafe(6)
        self.set_password(password)
        self._generated_password = password
        return password

    def set_password(self, password: str) -> None:
        cleaned = (password or "").strip()
        if len(cleaned) < 6:
            raise ValueError("Password must be at least 6 characters")
        salt = secrets.token_hex(16)
        self._data["password_salt"] = salt
        self._data["password_hash"] = hash_password(cleaned, salt)
        self._generated_password = None
        self.save()

    def verify_password(self, password: str) -> bool:
        salt = str(self._data.get("password_salt") or "")
        stored = str(self._data.get("password_hash") or "")
        if not salt or not stored:
            return False
        return secrets_equal(stored, hash_password(password.strip(), salt))
