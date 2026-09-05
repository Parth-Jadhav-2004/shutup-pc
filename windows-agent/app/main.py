from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from api.auth import router as auth_router
from api.apps import router as apps_router
from api.health import router as health_router
from api.media import router as media_router
from api.power import router as power_router
from api.services import router as services_router
from api.status import router as status_router
from app.context import ctx
from config.settings import settings
from services.logging_service import configure_file_logging

APP_PAGE = (ROOT / "templates" / "app.html").read_text(encoding="utf-8")
SETUP_PAGE = (ROOT / "templates" / "setup.html").read_text(encoding="utf-8")
logger = configure_file_logging(settings.log_path)
QUIET_POLL_PATHS = {"/api/v1/status", "/api/v1/media/volume"}

app = FastAPI(title="Laptop Remote", version=settings.agent_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(apps_router, prefix="/api/v1")
app.include_router(status_router, prefix="/api/v1")
app.include_router(power_router, prefix="/api/v1")
app.include_router(services_router, prefix="/api/v1")
app.include_router(media_router, prefix="/api/v1")


@app.middleware("http")
async def log_request(request: Request, call_next):
    started_at = time.perf_counter()
    client_ip = request.client.host if request.client else "unknown"
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed method=%s path=%s client=%s duration_ms=%d",
            request.method,
            request.url.path,
            client_ip,
            int((time.perf_counter() - started_at) * 1000),
        )
        raise
    if response.status_code >= 400 or request.url.path not in QUIET_POLL_PATHS:
        logger.info(
            "request method=%s path=%s status=%d client=%s duration_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            client_ip,
            int((time.perf_counter() - started_at) * 1000),
        )
    return response


@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
def app_page() -> str:
    return APP_PAGE


@app.get("/setup", response_class=HTMLResponse)
def setup_page() -> str:
    return SETUP_PAGE


@app.get("/pair")
def setup_redirect() -> RedirectResponse:
    return RedirectResponse(url="/setup")


def print_banner() -> None:
    local_ip = ctx.network.local_ip()
    remote_url = ctx.network.remote_url(settings.port)
    generated = ctx.tokens.ensure_password()
    print("=" * 52)
    print(" Laptop Remote is running")
    print(f" Device: {ctx.tokens.device_name}")
    print(f" Local:  http://{local_ip}:{settings.port}")
    if remote_url:
        print(f" Remote: {remote_url}")
    else:
        print(" Remote: Tailscale HTTPS is not ready")
    print(f" Setup:  http://127.0.0.1:{settings.port}/setup")
    if generated:
        print(f" Password (save this): {generated}")
        print(" Change it on the setup page on this PC.")
    else:
        print(" Password: already set (change it at the setup page)")
    print(f" Logs:   {settings.log_path}")
    print("=" * 52)
    logger.info(
        "agent_started host=%s port=%d local_url=http://%s:%d tailscale_available=%s password_generated=%s",
        settings.host,
        settings.port,
        local_ip,
        settings.port,
        bool(remote_url),
        bool(generated),
    )


def run_tray() -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return

    image = Image.new("RGB", (64, 64), "#0B0D10")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=14, fill="#5B8DEF")
    draw.rectangle((20, 22, 44, 38), outline="white", width=3)

    def open_app(_icon, _item) -> None:
        webbrowser.open(f"http://127.0.0.1:{settings.port}/")

    def open_setup(_icon, _item) -> None:
        webbrowser.open(f"http://127.0.0.1:{settings.port}/setup")

    def exit_app(icon, _item) -> None:
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open control panel", open_app, default=True),
        pystray.MenuItem("Open setup page", open_setup),
        pystray.MenuItem("Quit", exit_app),
    )
    pystray.Icon("LaptopRemote", image, "Laptop Remote", menu).run()


def _ensure_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")


def main() -> None:
    _ensure_stdio()
    parser = argparse.ArgumentParser(description="Laptop Remote Windows web agent")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--open-setup", action="store_true")
    args = parser.parse_args()

    print_banner()
    if args.open_setup:
        webbrowser.open(f"http://127.0.0.1:{args.port}/setup")

    if not args.no_tray:
        threading.Thread(target=run_tray, daemon=True).start()

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
