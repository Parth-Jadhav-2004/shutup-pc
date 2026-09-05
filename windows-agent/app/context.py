from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings
from security.token_manager import TokenManager
from services.agent_services import AgentServices
from services.app_service import AppService
from services.auth_service import AuthService
from services.media_service import MediaService
from services.network_service import NetworkService
from services.power_service import PowerService
from services.telemetry_service import TelemetryService
from services.throttle import ThrottleService


@dataclass
class AppContext:
    tokens: TokenManager
    auth: AuthService
    network: NetworkService
    power: PowerService
    telemetry: TelemetryService
    media: MediaService
    services: AgentServices
    apps: AppService
    throttle: ThrottleService


def build_context() -> AppContext:
    tokens = TokenManager(settings.secrets_path, settings.hostname)
    return AppContext(
        tokens=tokens,
        auth=AuthService(tokens),
        network=NetworkService(),
        power=PowerService(),
        telemetry=TelemetryService(),
        media=MediaService(),
        services=AgentServices(agent_port=settings.port),
        apps=AppService(),
        throttle=ThrottleService(),
    )


ctx = build_context()
