from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import Diaper
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_local_datetime
from babytracker.services.daily import diaper_summary, format_ago

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

STOOL_COLORS = [
    ("yellow", "Gelb"),
    ("green", "Grün"),
    ("brown", "Braun"),
    ("black", "Schwarz"),
    ("white", "Weiss"),
    ("bloody", "Blutig"),
]
STOOL_CONSISTENCY = [
    ("liquid", "Flüssig"),
    ("mushy", "Breiig"),
    ("formed", "Geformt"),
    ("hard", "Hart"),
]
PEE_INTENSITY = [
    ("light", "Hell"),
    ("normal", "Normal"),
    ("dark", "Dunkel"),
]


def _redirect_to_setup(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/setup/child", status_code=303)


@router.get("/diaper", response_class=HTMLResponse)
async def diaper_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    today = datetime.now(TZ).date()
    summary = diaper_summary(session, child.id, today)
    recent = session.exec(
        select(Diaper)
        .where(Diaper.child_id == child.id)
        .order_by(Diaper.changed_at.desc())
        .limit(15)
    ).all()

    return templates.TemplateResponse(
        request,
        "diaper/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "summary": summary,
            "recent": recent,
            "format_ago": format_ago,
            "stool_colors": dict(STOOL_COLORS),
            "stool_consistency": dict(STOOL_CONSISTENCY),
            "pee_intensity": dict(PEE_INTENSITY),
        },
    )


@router.get("/diaper/new", response_class=HTMLResponse)
async def diaper_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    return templates.TemplateResponse(
        request,
        "diaper/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "now_local": now_local_iso(),
            "stool_colors": STOOL_COLORS,
            "stool_consistency": STOOL_CONSISTENCY,
            "pee_intensity": PEE_INTENSITY,
        },
    )


@router.post("/diaper/new")
async def diaper_create(
    request: Request,
    changed_at: str = Form(...),
    pee: str = Form(""),
    stool: str = Form(""),
    pee_intensity: str = Form(""),
    stool_color: str = Form(""),
    stool_consistency: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    try:
        dt = parse_local_datetime(changed_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    has_pee = bool(pee)
    has_stool = bool(stool)
    if not (has_pee or has_stool):
        raise HTTPException(status_code=400, detail="Pipi oder Stuhl auswählen")

    d = Diaper(
        child_id=child.id,
        changed_at=dt,
        pee=has_pee,
        stool=has_stool,
        pee_intensity=pee_intensity if has_pee and pee_intensity else None,
        stool_color=stool_color if has_stool and stool_color else None,
        stool_consistency=stool_consistency if has_stool and stool_consistency else None,
        notes=notes.strip() or None,
        created_by=get_user_id(session, user),
    )
    session.add(d)
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/diaper", status_code=303)
