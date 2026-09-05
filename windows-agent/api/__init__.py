from .auth import router as auth_router
from .health import router as health_router
from .power import router as power_router
from .status import router as status_router

__all__ = [
    "auth_router",
    "health_router",
    "power_router",
    "status_router",
]
