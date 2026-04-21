from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import Medication
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_local_datetime
from babytracker.services.daily import day_bounds_utc, format_ago

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

PRESETS = [
    {"name": "vitamin_d", "label": "Vitamin D3", "dose": 400.0, "unit": "IE", "route": "oral", "note": "täglich ab Tag 8"},
    {"name": "vitamin_k", "label": "Vitamin K", "dose": 2.0, "unit": "mg", "route": "oral", "note": "Tag 1 · 4 · 28"},
    {"name": "paracetamol", "label": "Paracetamol", "dose": 60.0, "unit": "mg", "route": "oral", "note": "nach Arztangabe"},
]
ROUTES = [
    ("oral", "Oral"),
    ("injection", "Injektion"),
    ("topical", "Topisch"),
]


def _redirect_to_setup(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/setup/child", status_code=303)


def _redirect_to_meds(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/meds", status_code=303)


def _vit_d_given_today(session: Session, child_id: int) -> bool:
    today = datetime.now(TZ).date()
    start, end = day_bounds_utc(today)
    return bool(
        session.exec(
            select(Medication)
            .where(
                Medication.child_id == child_id,
                Medication.med_name == "vitamin_d",
                Medication.given_at >= start,
                Medication.given_at < end,
            )
            .limit(1)
        ).first()
    )


@router.get("/meds", response_class=HTMLResponse)
async def meds_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    recent = session.exec(
        select(Medication)
        .where(Medication.child_id == child.id)
        .order_by(Medication.given_at.desc())
        .limit(20)
    ).all()

    return templates.TemplateResponse(
        request,
        "meds/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "recent": recent,
            "presets": PRESETS,
            "vit_d_done": _vit_d_given_today(session, child.id),
            "format_ago": format_ago,
        },
    )


@router.get("/meds/new", response_class=HTMLResponse)
async def meds_new(
    request: Request,
    preset: str = "",
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    chosen = next((p for p in PRESETS if p["name"] == preset), None)

    return templates.TemplateResponse(
        request,
        "meds/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "now_local": now_local_iso(),
            "presets": PRESETS,
            "chosen": chosen,
            "routes": ROUTES,
        },
    )


@router.post("/meds/new")
async def meds_create(
    request: Request,
    given_at: str = Form(...),
    med_name: str = Form(...),
    dose_value: float = Form(...),
    dose_unit: str = Form(...),
    route: str = Form("oral"),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    try:
        dt = parse_local_datetime(given_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    if not med_name.strip():
        raise HTTPException(status_code=400, detail="Medikament-Name fehlt")
    if dose_value <= 0:
        raise HTTPException(status_code=400, detail="Dosis muss > 0 sein")

    session.add(
        Medication(
            child_id=child.id,
            given_at=dt,
            med_name=med_name.strip(),
            dose_value=dose_value,
            dose_unit=dose_unit.strip() or "IE",
            route=route if route in {"oral", "injection", "topical"} else "oral",
            notes=notes.strip() or None,
            created_by=get_user_id(session, user),
        )
    )
    session.commit()
    return _redirect_to_meds(request)


@router.post("/meds/quick/{preset_name}")
async def meds_quick(
    request: Request,
    preset_name: str,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Ein-Klick-Verabreichung eines Presets mit Uhrzeit=jetzt."""
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)

    preset = next((p for p in PRESETS if p["name"] == preset_name), None)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset unbekannt")

    session.add(
        Medication(
            child_id=child.id,
            given_at=datetime.now(TZ),
            med_name=preset["name"],
            dose_value=preset["dose"],
            dose_unit=preset["unit"],
            route=preset["route"],
            created_by=get_user_id(session, user),
        )
    )
    session.commit()
    return _redirect_to_meds(request)


@router.post("/meds/{med_id}/delete")
async def meds_delete(
    request: Request,
    med_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = get_child(session)
    if not child:
        return _redirect_to_setup(request)
    m = session.get(Medication, med_id)
    if m and m.child_id == child.id:
        session.delete(m)
        session.commit()
    return _redirect_to_meds(request)
