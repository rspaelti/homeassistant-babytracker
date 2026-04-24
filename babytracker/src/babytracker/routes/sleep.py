from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import SleepSession
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_past_datetime
from babytracker.services.daily import format_ago, format_duration, format_elapsed, sleep_summary

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

LOCATIONS = [
    ("co-sleeper", "Beistellbett"),
    ("crib", "Wiege"),
    ("arms", "Arm"),
    ("stroller", "Kinderwagen"),
    ("car", "Auto"),
]


def _redirect_to_setup(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/setup/child", status_code=303)


def _redirect_to_sleep(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/sleep", status_code=303)


@router.get("/sleep", response_class=HTMLResponse)
async def sleep_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    today = datetime.now(TZ).date()
    summary = sleep_summary(session, child.id, today)
    recent = session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child.id)
        .order_by(SleepSession.started_at.desc())
        .limit(15)
    ).all()

    return templates.TemplateResponse(
        request,
        "sleep/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "summary": summary,
            "recent": recent,
            "now": datetime.now(TZ),
            "locations": dict(LOCATIONS),
            "format_ago": format_ago,
            "format_duration": format_duration,
            "format_elapsed": format_elapsed,
        },
    )


@router.post("/sleep/start")
async def sleep_start(
    request: Request,
    location: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    active = session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child.id)
        .where(SleepSession.ended_at.is_(None))
    ).first()
    if active:
        return _redirect_to_sleep(request)

    s = SleepSession(
        child_id=child.id,
        started_at=datetime.now(TZ),
        location=location or None,
        created_by=get_user_id(session, user),
    )
    session.add(s)
    session.commit()
    return _redirect_to_sleep(request)


@router.post("/sleep/stop")
async def sleep_stop(
    request: Request,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    active = session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child.id)
        .where(SleepSession.ended_at.is_(None))
        .order_by(SleepSession.started_at.desc())
    ).first()
    if active:
        active.ended_at = datetime.now(TZ)
        session.add(active)
        session.commit()
    return _redirect_to_sleep(request)


@router.get("/sleep/{sleep_id}/edit", response_class=HTMLResponse)
async def sleep_edit_form(
    request: Request,
    sleep_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    entry = session.get(SleepSession, sleep_id)
    if not entry or entry.child_id != child.id:
        return _redirect_to_sleep(request)
    started_local = entry.started_at
    if started_local.tzinfo is None:
        started_local = started_local.replace(tzinfo=TZ)
    ended_local_iso = ""
    if entry.ended_at:
        e = entry.ended_at if entry.ended_at.tzinfo else entry.ended_at.replace(tzinfo=TZ)
        ended_local_iso = e.astimezone(TZ).strftime("%Y-%m-%dT%H:%M")
    return templates.TemplateResponse(
        request, "sleep/new.html",
        {
            "user": user, "version": request.app.version,
            "child_name": child.name,
            "now_local": started_local.astimezone(TZ).strftime("%Y-%m-%dT%H:%M"),
            "now_local_max": now_local_iso(),
            "ended_local": ended_local_iso,
            "locations": LOCATIONS,
            "entry": entry, "is_edit": True,
        },
    )


@router.post("/sleep/{sleep_id}/edit")
async def sleep_edit_save(
    request: Request,
    sleep_id: int,
    started_at: str = Form(...),
    ended_at: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    entry = session.get(SleepSession, sleep_id)
    if not entry or entry.child_id != child.id:
        return _redirect_to_sleep(request)
    try:
        started = parse_past_datetime(started_at)
        ended = parse_past_datetime(ended_at) if ended_at else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")
    if ended and ended <= started:
        raise HTTPException(status_code=400, detail="Endzeit muss nach Startzeit liegen")
    entry.started_at = started
    entry.ended_at = ended
    entry.location = location or None
    entry.notes = notes.strip() or None
    session.add(entry)
    session.commit()
    return _redirect_to_sleep(request)


@router.post("/sleep/{sleep_id}/delete")
async def sleep_delete(
    request: Request,
    sleep_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    s = session.get(SleepSession, sleep_id)
    if s and s.child_id == child.id:
        session.delete(s)
        session.commit()
    return _redirect_to_sleep(request)


@router.get("/sleep/new", response_class=HTMLResponse)
async def sleep_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    return templates.TemplateResponse(
        request,
        "sleep/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "now_local": now_local_iso(),
            "locations": LOCATIONS,
        },
    )


@router.post("/sleep/new")
async def sleep_create(
    request: Request,
    started_at: str = Form(...),
    ended_at: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    try:
        started = parse_past_datetime(started_at)
        ended = parse_past_datetime(ended_at) if ended_at else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    if ended and ended <= started:
        raise HTTPException(status_code=400, detail="Endzeit muss nach Startzeit liegen")

    s = SleepSession(
        child_id=child.id,
        started_at=started,
        ended_at=ended,
        location=location or None,
        notes=notes.strip() or None,
        created_by=get_user_id(session, user),
    )
    session.add(s)
    session.commit()
    return _redirect_to_sleep(request)
