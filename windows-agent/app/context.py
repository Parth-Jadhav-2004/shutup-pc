from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings
from security.token_manager import TokenManager
from services.auth_service import AuthService
from services.network_service import NetworkService
from services.power_service import PowerService
from services.telemetry_service import TelemetryService


@dataclass
class AppContext:
    tokens: TokenManager
    auth: AuthService
    network: NetworkService
    power: PowerService
    telemetry: TelemetryService


def build_context() -> AppContext:
    tokens = TokenManager(settings.secrets_path, settings.hostname)
    return AppContext(
        tokens=tokens,
        auth=AuthService(tokens),
        network=NetworkService(),
        power=PowerService(),
        telemetry=TelemetryService(),
    )


ctx = build_context()
