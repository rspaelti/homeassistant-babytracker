from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.routes._shared import TZ, get_child
from babytracker.services.timeline import (
    CATEGORY_KEYS,
    CATEGORY_LABELS,
    category_totals,
    custom_range_utc,
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
    range: str = "today",  # today / yesterday / 7d / custom
    date_from: str = Query("", alias="from"),
    date_to: str = Query("", alias="to"),
    cat: list[str] = Query(default_factory=list),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)

    now = datetime.now(TZ)
    today_iso = now.strftime("%Y-%m-%d")
    yesterday_iso = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago_iso = (now - timedelta(days=6)).strftime("%Y-%m-%d")

    if range == "7d":
        start, end = week_range_utc(now, days=7)
        label = "Letzte 7 Tage"
        eff_from = week_ago_iso
        eff_to = today_iso
    elif range == "yesterday":
        start, end = day_range_utc(yesterday_iso)
        label = "Gestern"
        eff_from = yesterday_iso
        eff_to = yesterday_iso
    elif range == "custom":
        eff_from = date_from or week_ago_iso
        eff_to = date_to or today_iso
        try:
            start, end = custom_range_utc(eff_from, eff_to)
            label = f"{eff_from} – {eff_to}" if eff_from != eff_to else eff_from
        except ValueError:
            start, end = day_range_utc(today_iso)
            label = "Heute"
            range = "today"
            eff_from = today_iso
            eff_to = today_iso
    else:
        range = "today"
        start, end = day_range_utc(today_iso)
        label = "Heute"
        eff_from = today_iso
        eff_to = today_iso

    active_cats = [c for c in cat if c in CATEGORY_LABELS]
    events = events_for_range(session, child, start, end, set(active_cats) if active_cats else None)
    grouped = group_by_day(events)
    totals = category_totals(session, child, start, end, active_cats)

    return templates.TemplateResponse(
        request,
        "timeline/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "range": range,
            "label": label,
            "today_iso": today_iso,
            "date_from": eff_from,
            "date_to": eff_to,
            "grouped": grouped,
            "count": len(events),
            "active_cats": active_cats,
            "category_keys": CATEGORY_KEYS,
            "category_labels": CATEGORY_LABELS,
            "totals": totals,
        },
    )
