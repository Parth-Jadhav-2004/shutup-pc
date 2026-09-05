from fastapi import APIRouter, HTTPException, Request

from app.context import ctx

router = APIRouter()


def _require(request: Request) -> None:
    ctx.auth.client_from_header(request.headers.get("authorization"))


@router.get("/apps")
def list_apps(request: Request) -> dict:
    _require(request)
    try:
        return {"apps": ctx.apps.list_apps()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"App scan failed: {exc}") from exc


@router.post("/apps/{app_id}/start")
def start_app(app_id: str, request: Request) -> dict:
    _require(request)
    try:
        return ctx.apps.start(app_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Start failed: {exc}") from exc


@router.post("/apps/{app_id}/stop")
def stop_app(app_id: str, request: Request) -> dict:
    _require(request)
    try:
        return ctx.apps.stop(app_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stop failed: {exc}") from exc


@router.post("/apps/{app_id}/toggle")
def toggle_app(app_id: str, request: Request) -> dict:
    _require(request)
    try:
        result = ctx.apps.toggle(app_id)
        result["apps"] = ctx.apps.list_apps()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Toggle failed: {exc}") from exc
