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
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_past_datetime
from babytracker.services.daily import diaper_summary, format_ago

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

# Stuhlfarben angelehnt an die Stool Color Card (Gallengangatresie-Screening).
# Normal = gelb/braun/grün. Alarm = blass/weiss/grau/schwarz (nach Mekonium)/blutig.
STOOL_COLOR_ORDER = [
    "mustard", "yellow", "green", "brown_light", "brown", "brown_dark",
    "pale", "white", "grey", "black", "bloody",
]
STOOL_COLORS_META: dict[str, dict] = {
    "mustard":     {"label": "Senfgelb",   "hex": "#d9a84a", "status": "normal",   "note": "typischer Muttermilchstuhl"},
    "yellow":      {"label": "Gelb",       "hex": "#e8c347", "status": "normal",   "note": "normal"},
    "green":       {"label": "Grün",       "hex": "#5b7b3a", "status": "normal",   "note": "normal (z.B. Eisenpräparat)"},
    "brown_light": {"label": "Hellbraun",  "hex": "#a8865a", "status": "normal",   "note": "normal"},
    "brown":       {"label": "Braun",      "hex": "#7a5a3a", "status": "normal",   "note": "normal"},
    "brown_dark":  {"label": "Dunkelbraun","hex": "#4d3824", "status": "normal",   "note": "normal"},
    "pale":        {"label": "Blass/Creme","hex": "#d9c8a8", "status": "warn",     "note": "⚠ Kinderarzt kontaktieren"},
    "white":       {"label": "Weiss",      "hex": "#e8e4d4", "status": "warn",     "note": "⚠ Kinderarzt kontaktieren"},
    "grey":        {"label": "Grau",       "hex": "#bcbab0", "status": "warn",     "note": "⚠ Kinderarzt kontaktieren"},
    "black":       {"label": "Schwarz",    "hex": "#1a1a1a", "status": "warn",     "note": "⚠ nach Mekonium auffällig"},
    "bloody":      {"label": "Blutig",     "hex": "#a02020", "status": "critical", "note": "⚠ sofort Arzt"},
}

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
AMOUNT = [
    ("light", "Wenig"),
    ("normal", "Normal"),
    ("heavy", "Viel"),
]


def _redirect_to_setup(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/setup/child", status_code=303)


def _redirect_to_diaper(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/diaper", status_code=303)


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
            "stool_colors_meta": STOOL_COLORS_META,
            "stool_consistency": dict(STOOL_CONSISTENCY),
            "pee_intensity": dict(PEE_INTENSITY),
            "amount_labels": dict(AMOUNT),
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

    normal_colors = [(k, STOOL_COLORS_META[k]) for k in STOOL_COLOR_ORDER if STOOL_COLORS_META[k]["status"] == "normal"]
    warn_colors = [(k, STOOL_COLORS_META[k]) for k in STOOL_COLOR_ORDER if STOOL_COLORS_META[k]["status"] != "normal"]

    return templates.TemplateResponse(
        request,
        "diaper/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "now_local": now_local_iso(),
            "normal_colors": normal_colors,
            "warn_colors": warn_colors,
            "stool_consistency": STOOL_CONSISTENCY,
            "pee_intensity": PEE_INTENSITY,
            "amount": AMOUNT,
        },
    )


@router.post("/diaper/new")
async def diaper_create(
    request: Request,
    changed_at: str = Form(...),
    pee: str = Form(""),
    stool: str = Form(""),
    pee_intensity: str = Form(""),
    pee_amount: str = Form(""),
    stool_color: str = Form(""),
    stool_consistency: str = Form(""),
    stool_amount: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    try:
        dt = parse_past_datetime(changed_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    has_pee = bool(pee)
    has_stool = bool(stool)
    if not (has_pee or has_stool):
        raise HTTPException(status_code=400, detail="Pipi oder Stuhl auswählen")

    if stool_color and stool_color not in STOOL_COLORS_META:
        raise HTTPException(status_code=400, detail="Unbekannte Stuhlfarbe")

    amount_vals = dict(AMOUNT)
    d = Diaper(
        child_id=child.id,
        changed_at=dt,
        pee=has_pee,
        stool=has_stool,
        pee_intensity=pee_intensity if has_pee and pee_intensity else None,
        pee_amount=pee_amount if has_pee and pee_amount in amount_vals else None,
        stool_color=stool_color if has_stool and stool_color else None,
        stool_consistency=stool_consistency if has_stool and stool_consistency else None,
        stool_amount=stool_amount if has_stool and stool_amount in amount_vals else None,
        notes=notes.strip() or None,
        created_by=get_user_id(session, user),
    )
    session.add(d)
    session.commit()

    return _redirect_to_diaper(request)


@router.post("/diaper/{diaper_id}/delete")
async def diaper_delete(
    request: Request,
    diaper_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    d = session.get(Diaper, diaper_id)
    if d and d.child_id == child.id:
        session.delete(d)
        session.commit()
    return _redirect_to_diaper(request)
