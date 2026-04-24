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

    # Bucket-Abstand 10 min → Lücke ab >15 min als null-Punkt einfügen,
    # damit Chart.js die Linie über fehlende Perioden (Socke aus) nicht durchzieht.
    gap_threshold = timedelta(minutes=15)
    series: dict[str, list[tuple[str, float | None]]] = {
        "spo2": [], "heart_rate": [], "temp_skin": [],
    }
    last_dt: dict[str, datetime] = {}
    for r in rows:
        if r.kind not in series:
            continue
        dt = as_aware(r.measured_at).astimezone(TZ)
        prev = last_dt.get(r.kind)
        if prev is not None and dt - prev > gap_threshold:
            # Null-Punkt kurz nach dem letzten Wert → unterbricht die Linie
            series[r.kind].append(((prev + timedelta(minutes=1)).isoformat(), None))
        series[r.kind].append((dt.isoformat(), r.value))
        last_dt[r.kind] = dt

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
