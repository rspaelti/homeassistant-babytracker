from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.config import settings
from babytracker.db import get_session
from babytracker.models import Vital
from babytracker.routes._shared import get_child
from babytracker.services.daily import as_aware, format_ago
from babytracker.services.owlet_sync import fetch_live

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

TZ = ZoneInfo(settings.timezone)


@router.get("/vitals", response_class=HTMLResponse)
async def vitals_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)

    now = datetime.now(TZ)
    since = now - timedelta(hours=24)

    rows = session.exec(
        select(Vital)
        .where(Vital.child_id == child.id, Vital.source == "owlet", Vital.agg == "avg")
        .where(Vital.measured_at >= since)
        .order_by(Vital.measured_at)
    ).all()

    series: dict[str, list[tuple[str, float]]] = {"spo2": [], "heart_rate": [], "temp_skin": []}
    for r in rows:
        if r.kind not in series:
            continue
        t = as_aware(r.measured_at).astimezone(TZ).isoformat()
        series[r.kind].append((t, r.value))

    live = await fetch_live()

    return templates.TemplateResponse(
        request,
        "vitals/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "series": series,
            "live": live,
            "format_ago": format_ago,
        },
    )
