from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import HealthEvent, Vital
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_past_datetime
from babytracker.services.daily import as_aware, format_ago

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

# Kategorien
CATEGORIES = [
    ("temp", "🌡️ Temperatur", "vital"),
    ("jaundice", "🟡 Ikterus", "event"),
    ("umbilical", "🩹 Nabel", "event"),
    ("skin", "🧴 Haut", "event"),
    ("crying", "😭 Schreiphase", "event"),
]
CATEGORY_LABELS = {k: lbl for k, lbl, _ in CATEGORIES}
CATEGORY_TYPES = {k: t for k, _, t in CATEGORIES}

JAUNDICE_LEVELS = [
    (0, "Keine", "bg-emerald-500"),
    (1, "Gesicht", "bg-yellow-300"),
    (2, "Oberkörper", "bg-amber-400"),
    (3, "Ganzkörper", "bg-rose-500"),
]
UMBILICAL_STATUS = [
    ("wet", "Feucht"),
    ("dry", "Trocken"),
    ("detached", "Abgefallen"),
    ("red", "Gerötet"),
    ("secretion", "Sekret"),
]
SKIN_STATUS = [
    ("ok", "Ok"),
    ("wound", "Wunde"),
    ("rash", "Ausschlag"),
    ("diaper_rash", "Windelrose"),
]


def _redirect_to_setup(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/setup/child", status_code=303)


def _redirect_to_health(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/health", status_code=303)


def _fever_threshold_info(child_age_days: int) -> tuple[float, str]:
    """Gibt (threshold_celsius, label) für Fieber-Warnung."""
    if child_age_days < 90:
        return 38.0, "<3 Monate: ≥ 38 °C = sofort Arzt / Notfall"
    if child_age_days < 180:
        return 38.0, "3–6 Monate: ≥ 38 °C = Arzt"
    return 38.5, ">6 Monate: ≥ 38.5 °C = Arzt"


@router.get("/health", response_class=HTMLResponse)
async def health_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    recent_events = session.exec(
        select(HealthEvent)
        .where(HealthEvent.child_id == child.id)
        .order_by(HealthEvent.recorded_at.desc())
        .limit(10)
    ).all()
    recent_temps = session.exec(
        select(Vital)
        .where(Vital.child_id == child.id, Vital.kind == "temp_body")
        .order_by(Vital.measured_at.desc())
        .limit(10)
    ).all()

    last_temp = recent_temps[0] if recent_temps else None

    age_days = int((as_aware(datetime.now(TZ)) - as_aware(child.birth_at)).total_seconds() / 86400)
    fever_th, fever_label = _fever_threshold_info(age_days)

    return templates.TemplateResponse(
        request,
        "health/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "recent_events": recent_events,
            "recent_temps": recent_temps,
            "last_temp": last_temp,
            "categories": CATEGORIES,
            "category_labels": CATEGORY_LABELS,
            "umbilical_status": dict(UMBILICAL_STATUS),
            "skin_status": dict(SKIN_STATUS),
            "jaundice_levels": {lvl: label for lvl, label, _ in JAUNDICE_LEVELS},
            "fever_threshold": fever_th,
            "fever_label": fever_label,
            "format_ago": format_ago,
        },
    )


@router.get("/health/new", response_class=HTMLResponse)
async def health_new(
    request: Request,
    category: str = "temp",
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if category not in CATEGORY_LABELS:
        category = "temp"
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    age_days = int((as_aware(datetime.now(TZ)) - as_aware(child.birth_at)).total_seconds() / 86400)
    fever_th, fever_label = _fever_threshold_info(age_days)

    return templates.TemplateResponse(
        request,
        "health/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "category": category,
            "category_label": CATEGORY_LABELS[category],
            "categories": CATEGORIES,
            "now_local": now_local_iso(),
            "jaundice_levels": JAUNDICE_LEVELS,
            "umbilical_status": UMBILICAL_STATUS,
            "skin_status": SKIN_STATUS,
            "fever_threshold": fever_th,
            "fever_label": fever_label,
        },
    )


@router.post("/health/new")
async def health_create(
    request: Request,
    category: str = Form(...),
    recorded_at: str = Form(...),
    temp_value: float = Form(0.0),
    score: int = Form(-1),
    status_value: str = Form(""),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if category not in CATEGORY_LABELS:
        raise HTTPException(status_code=400, detail="Unbekannte Kategorie")
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    try:
        dt = parse_past_datetime(recorded_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    created_by = get_user_id(session, user)

    if category == "temp":
        if not (34.0 <= temp_value <= 42.0):
            raise HTTPException(status_code=400, detail="Temperatur muss 34–42 °C sein")
        session.add(
            Vital(
                child_id=child.id,
                measured_at=dt,
                kind="temp_body",
                value=temp_value,
                agg="instant",
                source="manual",
                created_by=created_by,
            )
        )
    else:
        e = HealthEvent(
            child_id=child.id,
            recorded_at=dt,
            category=category,
            notes=notes.strip() or None,
            created_by=created_by,
        )
        if category == "jaundice":
            if not (0 <= score <= 3):
                raise HTTPException(status_code=400, detail="Ikterus-Score 0–3")
            e.score = score
        elif category == "umbilical":
            if status_value not in dict(UMBILICAL_STATUS):
                raise HTTPException(status_code=400, detail="Nabel-Status ungültig")
            e.status = status_value
        elif category == "skin":
            if status_value not in dict(SKIN_STATUS):
                raise HTTPException(status_code=400, detail="Haut-Status ungültig")
            e.status = status_value
        elif category == "crying":
            pass
        session.add(e)

    session.commit()
    return _redirect_to_health(request)


@router.post("/health/event/{event_id}/delete")
async def health_event_delete(
    request: Request,
    event_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    e = session.get(HealthEvent, event_id)
    if e and e.child_id == child.id:
        session.delete(e)
        session.commit()
    return _redirect_to_health(request)


@router.post("/health/temp/{vital_id}/delete")
async def health_temp_delete(
    request: Request,
    vital_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    v = session.get(Vital, vital_id)
    if v and v.child_id == child.id and v.kind == "temp_body":
        session.delete(v)
        session.commit()
    return _redirect_to_health(request)
