from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from babytracker import __version__
from babytracker.auth import CurrentUser, get_current_user
from babytracker.config import settings
from babytracker.routes import growth as growth_routes

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Baby-Tracker",
    version=__version__,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app.include_router(growth_routes.router)


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "version": __version__,
            "child_name": settings.default_child,
        },
    )
