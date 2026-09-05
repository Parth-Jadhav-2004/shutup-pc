from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.context import ctx

router = APIRouter()


class ToggleRequest(BaseModel):
    action: str = "toggle"


def _require(request: Request) -> None:
    ctx.auth.client_from_header(request.headers.get("authorization"))


@router.get("/services")
def list_services(request: Request) -> dict:
    _require(request)
    try:
        return {"services": ctx.services.list_services()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Service scan failed: {exc}") from exc


@router.post("/services/{service_id}/start")
def start_service(service_id: str, request: Request) -> dict:
    _require(request)
    try:
        return ctx.services.start(service_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Start failed: {exc}") from exc


@router.post("/services/{service_id}/stop")
def stop_service(service_id: str, request: Request) -> dict:
    _require(request)
    try:
        return ctx.services.stop(service_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stop failed: {exc}") from exc


@router.post("/services/{service_id}/toggle")
def toggle_service(service_id: str, request: Request, body: ToggleRequest | None = None) -> dict:
    _require(request)
    action = (body.action if body else "toggle").lower()
    try:
        if action == "start":
            return ctx.services.start(service_id)
        if action == "stop":
            return ctx.services.stop(service_id)
        result = ctx.services.toggle(service_id)
        services = ctx.services.list_services()
        result["services"] = services
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Toggle failed: {exc}") from exc
