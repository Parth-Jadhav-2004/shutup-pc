from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.context import ctx

router = APIRouter()


def _require(request: Request) -> None:
    ctx.auth.client_from_header(request.headers.get("authorization"))


@router.post("/power/lock")
def lock(request: Request) -> dict:
    _require(request)
    try:
        return ctx.power.lock()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lock could not be initiated. {exc}") from exc


@router.post("/power/sleep")
def sleep(request: Request, background_tasks: BackgroundTasks) -> dict:
    _require(request)
    background_tasks.add_task(ctx.power.sleep)
    return {"success": True, "message": "Sleep initiated"}


@router.post("/power/restart")
def restart(request: Request, background_tasks: BackgroundTasks) -> dict:
    _require(request)
    background_tasks.add_task(ctx.power.restart)
    return {"success": True, "message": "Restart initiated"}


@router.post("/power/shutdown")
def shutdown(request: Request, background_tasks: BackgroundTasks) -> dict:
    _require(request)
    background_tasks.add_task(ctx.power.shutdown)
    return {"success": True, "message": "Shutdown initiated"}
