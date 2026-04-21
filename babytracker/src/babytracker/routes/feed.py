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
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_local_datetime
from babytracker.services.daily import feed_summary, format_ago

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
        dt = parse_local_datetime(started_at)
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
