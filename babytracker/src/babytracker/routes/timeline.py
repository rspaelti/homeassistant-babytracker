from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.routes._shared import TZ, get_child
from babytracker.services.timeline import (
    day_range_utc,
    events_for_range,
    group_by_day,
    week_range_utc,
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/timeline", response_class=HTMLResponse)
async def timeline_index(
    request: Request,
    range: str = "today",  # today / yesterday / 7d / day (with ?date=)
    date: str = "",
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)

    now = datetime.now(TZ)
    if range == "7d":
        start, end = week_range_utc(now, days=7)
        label = "Letzte 7 Tage"
    elif range == "yesterday":
        y = (now - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
        start, end = day_range_utc(y)
        label = "Gestern"
    elif range == "day" and date:
        try:
            start, end = day_range_utc(date)
            label = date
        except ValueError:
            start, end = day_range_utc(now.strftime("%Y-%m-%d"))
            label = "Heute"
    else:
        start, end = day_range_utc(now.strftime("%Y-%m-%d"))
        label = "Heute"

    events = events_for_range(session, child, start, end)
    grouped = group_by_day(events)

    return templates.TemplateResponse(
        request,
        "timeline/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "range": range,
            "label": label,
            "today_iso": now.strftime("%Y-%m-%d"),
            "date": date,
            "grouped": grouped,
            "count": len(events),
        },
    )
