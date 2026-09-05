from .apps import router as apps_router
from .auth import router as auth_router
from .health import router as health_router
from .media import router as media_router
from .power import router as power_router
from .services import router as services_router
from .status import router as status_router
from .throttle import router as throttle_router

__all__ = [
    "apps_router",
    "auth_router",
    "health_router",
    "media_router",
    "power_router",
    "services_router",
    "status_router",
    "throttle_router",
]
