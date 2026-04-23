from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import Feeding
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_past_datetime
from babytracker.services.daily import feed_summary, format_ago
from babytracker.services.warnings import estimate_feed_interval

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

BOTTLE_TYPES = [
    ("breastmilk", "Muttermilch"),
    ("pre", "PRE"),
    ("1", "1er"),
    ("2", "2er"),
]


def _redirect_to_setup(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/setup/child", status_code=303)


@router.get("/feed", response_class=HTMLResponse)
async def feed_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    today = datetime.now(TZ).date()
    summary = feed_summary(session, child.id, today)

    recent = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .order_by(Feeding.started_at.desc())
        .limit(15)
    ).all()

    now = datetime.now(TZ)
    est = estimate_feed_interval(session, child, now)
    next_in_min: int | None = None
    if summary.last_at and summary.last_at <= now:
        from_last = (now - summary.last_at).total_seconds() / 3600
        next_in_min = int((est.hours - from_last) * 60)

    return templates.TemplateResponse(
        request,
        "feed/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "summary": summary,
            "recent": recent,
            "format_ago": format_ago,
            "interval_hours": est.hours,
            "interval_base": est.base_hours,
            "interval_reasons": est.reasons,
            "next_in_min": next_in_min,
        },
    )


@router.get("/feed/new", response_class=HTMLResponse)
async def feed_new(
    request: Request,
    kind: str = "breast",
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if kind not in ("breast", "bottle"):
        kind = "breast"
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    last_breast = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id, Feeding.kind == "breast")
        .order_by(Feeding.started_at.desc())
    ).first()
    last_side = last_breast.breast_side if last_breast else None
    default_side = "right" if last_side == "left" else "left"

    return templates.TemplateResponse(
        request,
        "feed/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "kind": kind,
            "now_local": now_local_iso(),
            "default_side": default_side,
            "bottle_types": BOTTLE_TYPES,
        },
    )


@router.post("/feed/new")
async def feed_create(
    request: Request,
    kind: str = Form(...),
    started_at: str = Form(...),
    duration_left_min: int = Form(0),
    duration_right_min: int = Form(0),
    breast_side_primary: str = Form("left"),
    bottle_type: str = Form(""),
    bottle_offered_ml: int = Form(0),
    bottle_taken_ml: int = Form(0),
    spit_up: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if kind not in ("breast", "bottle"):
        raise HTTPException(status_code=400, detail="kind muss breast oder bottle sein")

    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    try:
        dt = parse_past_datetime(started_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    feed = Feeding(
        child_id=child.id,
        started_at=dt,
        ended_at=None,
        kind=kind,
        notes=notes.strip() or None,
        spit_up=bool(spit_up),
        created_by=get_user_id(session, user),
    )

    if kind == "breast":
        if duration_left_min < 0 or duration_right_min < 0:
            raise HTTPException(status_code=400, detail="Dauern dürfen nicht negativ sein")
        if duration_left_min > 90 or duration_right_min > 90:
            raise HTTPException(status_code=400, detail="Max. 90 Min. pro Seite")
        feed.duration_left_min = duration_left_min or None
        feed.duration_right_min = duration_right_min or None
        total = duration_left_min + duration_right_min
        if duration_left_min and duration_right_min:
            feed.breast_side = "both"
        elif duration_left_min:
            feed.breast_side = "left"
        elif duration_right_min:
            feed.breast_side = "right"
        else:
            feed.breast_side = breast_side_primary
        if total > 0:
            feed.ended_at = dt.fromtimestamp(dt.timestamp() + total * 60, tz=dt.tzinfo)
    else:
        if bottle_offered_ml < 0 or bottle_offered_ml > 400:
            raise HTTPException(status_code=400, detail="Flaschenmenge 0–400 ml")
        if bottle_taken_ml < 0 or bottle_taken_ml > 400:
            raise HTTPException(status_code=400, detail="Flaschenmenge 0–400 ml")
        feed.bottle_type = bottle_type or None
        feed.bottle_offered_ml = bottle_offered_ml or None
        feed.bottle_taken_ml = bottle_taken_ml or None

    session.add(feed)
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/feed", status_code=303)


def _apply_feeding(
    f: Feeding,
    *,
    kind: str,
    dt: datetime,
    duration_left_min: int,
    duration_right_min: int,
    breast_side_primary: str,
    bottle_type: str,
    bottle_offered_ml: int,
    bottle_taken_ml: int,
    spit_up: bool,
    notes: str,
) -> None:
    f.started_at = dt
    f.kind = kind
    f.spit_up = spit_up
    f.notes = notes.strip() or None
    if kind == "breast":
        if duration_left_min < 0 or duration_right_min < 0:
            raise HTTPException(status_code=400, detail="Dauern dürfen nicht negativ sein")
        if duration_left_min > 90 or duration_right_min > 90:
            raise HTTPException(status_code=400, detail="Max. 90 Min. pro Seite")
        f.duration_left_min = duration_left_min or None
        f.duration_right_min = duration_right_min or None
        total = duration_left_min + duration_right_min
        if duration_left_min and duration_right_min:
            f.breast_side = "both"
        elif duration_left_min:
            f.breast_side = "left"
        elif duration_right_min:
            f.breast_side = "right"
        else:
            f.breast_side = breast_side_primary
        f.ended_at = dt.fromtimestamp(dt.timestamp() + total * 60, tz=dt.tzinfo) if total > 0 else None
        f.bottle_type = None
        f.bottle_offered_ml = None
        f.bottle_taken_ml = None
    else:
        if bottle_offered_ml < 0 or bottle_offered_ml > 400:
            raise HTTPException(status_code=400, detail="Flaschenmenge 0–400 ml")
        if bottle_taken_ml < 0 or bottle_taken_ml > 400:
            raise HTTPException(status_code=400, detail="Flaschenmenge 0–400 ml")
        f.bottle_type = bottle_type or None
        f.bottle_offered_ml = bottle_offered_ml or None
        f.bottle_taken_ml = bottle_taken_ml or None
        f.duration_left_min = None
        f.duration_right_min = None
        f.breast_side = None
        f.ended_at = None


@router.get("/feed/{feed_id}/edit", response_class=HTMLResponse)
async def feed_edit_form(
    request: Request,
    feed_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    entry = session.get(Feeding, feed_id)
    if not entry or entry.child_id != child.id:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/feed", status_code=303)

    started_local = entry.started_at
    if started_local.tzinfo is None:
        started_local = started_local.replace(tzinfo=TZ)
    return templates.TemplateResponse(
        request,
        "feed/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "kind": entry.kind,
            "now_local": started_local.astimezone(TZ).strftime("%Y-%m-%dT%H:%M"),
            "now_local_max": now_local_iso(),
            "default_side": entry.breast_side or "left",
            "bottle_types": BOTTLE_TYPES,
            "entry": entry,
            "is_edit": True,
        },
    )


@router.post("/feed/{feed_id}/edit")
async def feed_edit_save(
    request: Request,
    feed_id: int,
    kind: str = Form(...),
    started_at: str = Form(...),
    duration_left_min: int = Form(0),
    duration_right_min: int = Form(0),
    breast_side_primary: str = Form("left"),
    bottle_type: str = Form(""),
    bottle_offered_ml: int = Form(0),
    bottle_taken_ml: int = Form(0),
    spit_up: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if kind not in ("breast", "bottle"):
        raise HTTPException(status_code=400, detail="kind muss breast oder bottle sein")
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    entry = session.get(Feeding, feed_id)
    if not entry or entry.child_id != child.id:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/feed", status_code=303)
    try:
        dt = parse_past_datetime(started_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    _apply_feeding(
        entry,
        kind=kind, dt=dt,
        duration_left_min=duration_left_min,
        duration_right_min=duration_right_min,
        breast_side_primary=breast_side_primary,
        bottle_type=bottle_type,
        bottle_offered_ml=bottle_offered_ml,
        bottle_taken_ml=bottle_taken_ml,
        spit_up=bool(spit_up),
        notes=notes,
    )
    session.commit()
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/feed", status_code=303)


@router.post("/feed/{feed_id}/delete")
async def feed_delete(
    request: Request,
    feed_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    f = session.get(Feeding, feed_id)
    if f and f.child_id == child.id:
        session.delete(f)
        session.commit()
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/feed", status_code=303)
