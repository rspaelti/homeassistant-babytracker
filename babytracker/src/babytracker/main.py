from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.middleware.base import BaseHTTPMiddleware

from babytracker import __version__
from babytracker.auth import CurrentUser, get_current_user
from babytracker.config import settings  # noqa: F401  # keep env/side effects
from babytracker.db import engine, get_session
from babytracker.models import Child, Measurement, Medication, MotherLog, Vital, WarningState
from babytracker.services.timeline import day_range_utc, events_for_range
from babytracker.services.warnings import estimate_feed_interval
from babytracker.routes import diaper as diaper_routes
from babytracker.routes import feed as feed_routes
from babytracker.routes import growth as growth_routes
from babytracker.routes import health as health_routes
from babytracker.routes import meds as meds_routes
from babytracker.routes import more as more_routes
from babytracker.routes import mother as mother_routes
from babytracker.routes import notes as notes_routes
from babytracker.routes import placeholders as placeholder_routes
from babytracker.routes import quick as quick_routes
from babytracker.routes import setup as setup_routes
from babytracker.routes import sleep as sleep_routes
from babytracker.routes import timeline as timeline_routes
from babytracker.routes import warnings as warnings_routes
from babytracker.scheduler import start_scheduler, stop_scheduler
from babytracker.services.daily import (
    diaper_summary,
    feed_summary,
    format_ago,
    format_duration,
    sleep_summary,
)

TZ = ZoneInfo(settings.timezone)


class IngressPathMiddleware(BaseHTTPMiddleware):
    """Liest X-Ingress-Path-Header und setzt ihn als root_path.

    Dadurch funktioniert die App sowohl direkt (localhost) als auch hinter
    HA-Ingress (`/api/hassio_ingress/<token>/...`). Templates nutzen
    `request.scope.root_path` als Präfix für alle internen Links.
    """

    async def dispatch(self, request, call_next):
        ingress_path = request.headers.get("x-ingress-path", "")
        if ingress_path:
            request.scope["root_path"] = ingress_path
        return await call_next(request)


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

app.add_middleware(IngressPathMiddleware)

STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

app.include_router(growth_routes.router)
app.include_router(setup_routes.router)
app.include_router(feed_routes.router)
app.include_router(diaper_routes.router)
app.include_router(sleep_routes.router)
app.include_router(health_routes.router)
app.include_router(meds_routes.router)
app.include_router(mother_routes.router)
app.include_router(notes_routes.router)
app.include_router(timeline_routes.router)
app.include_router(quick_routes.router)
app.include_router(warnings_routes.router)
app.include_router(more_routes.router)
app.include_router(placeholder_routes.router)


def _from_json(value: str | None):
    if not value:
        return {}
    import json as _json

    try:
        return _json.loads(value)
    except (ValueError, TypeError):
        return {}


templates.env.filters["from_json"] = _from_json


@app.on_event("startup")
async def _startup() -> None:
    from babytracker.scripts.seed import seed_if_empty
    seed_if_empty()
    start_scheduler()


@app.on_event("shutdown")
async def _shutdown() -> None:
    stop_scheduler()


def _age_label(birth_at: datetime) -> str:
    now = datetime.now(TZ)
    if birth_at.tzinfo is None:
        birth_at = birth_at.replace(tzinfo=TZ)
    delta = now - birth_at
    days = int(delta.total_seconds() / 86400)
    if days < 1:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours} Stunden alt"
    if days < 14:
        return f"{days} Tage alt"
    if days < 90:
        weeks = days // 7
        rest = days % 7
        return f"{weeks} Wochen{f', {rest} Tage' if rest else ''} alt"
    months = days // 30
    return f"~{months} Monate alt"


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    child = session.exec(
        select(Child).where(Child.active == True).order_by(Child.id)  # noqa: E712
    ).first()

    ctx: dict = {
        "user": user,
        "version": __version__,
        "child_name": child.name if child else "Baby",
        "show_dashboard": bool(child),
        "age_label": _age_label(child.birth_at) if child else None,
        "format_ago": format_ago,
        "format_duration": format_duration,
    }

    if child:
        today = datetime.now(TZ).date()
        ctx["feed_summary"] = feed_summary(session, child.id, today)
        ctx["diaper_summary"] = diaper_summary(session, child.id, today)
        ctx["sleep_summary"] = sleep_summary(session, child.id, today)

        latest_w = session.exec(
            select(Measurement)
            .where(Measurement.child_id == child.id, Measurement.kind == "weight")
            .order_by(Measurement.measured_at.desc())
        ).first()
        ctx["latest_weight"] = f"{int(latest_w.value)} g" if latest_w else None

        latest_temp = session.exec(
            select(Vital)
            .where(Vital.child_id == child.id, Vital.kind == "temp_body")
            .order_by(Vital.measured_at.desc())
        ).first()
        ctx["latest_temp"] = latest_temp

        from babytracker.services.daily import day_bounds_utc
        start_d, end_d = day_bounds_utc(today)
        vit_d_today = session.exec(
            select(Medication)
            .where(
                Medication.child_id == child.id,
                Medication.med_name == "vitamin_d",
                Medication.given_at >= start_d,
                Medication.given_at < end_d,
            )
            .limit(1)
        ).first()
        ctx["vit_d_done"] = bool(vit_d_today)

        # Mama: Clexane heute?
        clexane_today = session.exec(
            select(MotherLog)
            .where(
                MotherLog.category == "clexane",
                MotherLog.logged_at >= start_d,
                MotherLog.logged_at < end_d,
            )
            .limit(1)
        ).first()
        ctx["mother_clexane_today"] = bool(clexane_today)

        # Heute-Events für Timeline-Kachel
        today_start, today_end = day_range_utc(today.strftime("%Y-%m-%d"))
        today_events = events_for_range(session, child, today_start, today_end)
        ctx["today_event_count"] = len(today_events)

        ctx["active_warnings"] = session.exec(
            select(WarningState).where(WarningState.active == True)  # noqa: E712
        ).all()

        # Dynamisches Still-Intervall → nächste empfohlene Mahlzeit
        now = datetime.now(TZ)
        est = estimate_feed_interval(session, child, now)
        ctx["feed_interval_hours"] = est.hours
        ctx["feed_interval_base"] = est.base_hours
        ctx["feed_interval_reasons"] = est.reasons
        last_at = ctx["feed_summary"].last_at
        if last_at and last_at <= now:
            from_last = (now - last_at).total_seconds() / 3600
            ctx["feed_next_in_min"] = int((est.hours - from_last) * 60)
        else:
            ctx["feed_next_in_min"] = None

    return templates.TemplateResponse(request, "home.html", ctx)
