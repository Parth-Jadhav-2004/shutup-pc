from __future__ import annotations

import json
import socket
import subprocess
from typing import Any

import psutil


class NetworkService:
    def local_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    def tailscale_ip(self) -> str | None:
        for addresses in psutil.net_if_addrs().values():
            for item in addresses:
                if item.family == socket.AF_INET and item.address.startswith("100."):
                    return item.address

        try:
            result = subprocess.run(
                ["tailscale", "ip", "-4"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode == 0:
                ip = result.stdout.strip().split()[0]
                if ip:
                    return ip
        except Exception:
            pass
        return None

    def tailscale_dns_name(self) -> str | None:
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode != 0:
                return None
            status = json.loads(result.stdout)
            dns_name = str(status.get("Self", {}).get("DNSName", "")).rstrip(".")
            return dns_name or None
        except Exception:
            return None

    def base_url(self, ip: str, port: int) -> str:
        return f"http://{ip}:{port}"

    def remote_url(self, port: int) -> str | None:
        dns_name = self.tailscale_dns_name()
        if dns_name:
            return f"https://{dns_name}/laptop-remote"
        remote_ip = self.tailscale_ip()
        return self.base_url(remote_ip, port) if remote_ip else None

    def diagnostics(self, *, port: int, sessions: int, extra: dict[str, Any]) -> dict[str, Any]:
        local_ip = self.local_ip()
        remote_ip = self.tailscale_ip()
        dns_name = self.tailscale_dns_name()
        return {
            "local_ip": local_ip,
            "tailscale_ip": remote_ip,
            "tailscale_dns_name": dns_name,
            "local_url": self.base_url(local_ip, port),
            "remote_url": f"https://{dns_name}/laptop-remote"
            if dns_name
            else (self.base_url(remote_ip, port) if remote_ip else None),
            "port": port,
            "sessions": sessions,
            **extra,
        }
