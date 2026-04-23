from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.config import settings
from babytracker.db import get_session
from babytracker.models import Child, Measurement, User
from babytracker.services.growth import (
    KIND_LABELS,
    KIND_UNITS,
    build_chart,
    display_value,
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

TZ = ZoneInfo(settings.timezone)


def _get_child(session: Session) -> Child | None:
    return session.exec(select(Child).where(Child.active == True).order_by(Child.id)).first()  # noqa: E712


def _get_user_id(session: Session, user: CurrentUser) -> int | None:
    db_user = session.exec(select(User).where(User.name == user.name)).first()
    return db_user.id if db_user else None


@router.get("/growth", response_class=HTMLResponse)
async def growth_index(
    request: Request,
    kind: str = "weight",
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if kind not in KIND_LABELS:
        kind = "weight"
    child = _get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)
    chart = build_chart(session, child, kind)

    latest = chart.points[-1] if chart.points else None

    return templates.TemplateResponse(
        request,
        "growth/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "child": child,
            "kind": kind,
            "kinds": list(KIND_LABELS.items()),
            "label": KIND_LABELS[kind],
            "unit": KIND_UNITS[kind],
            "chart": chart,
            "latest": latest,
            "display_value": display_value,
        },
    )


@router.get("/growth/new", response_class=HTMLResponse)
async def growth_new(
    request: Request,
    kind: str = "weight",
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if kind not in KIND_LABELS:
        kind = "weight"
    child = _get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)
    now_local = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M")
    return templates.TemplateResponse(
        request,
        "growth/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "kind": kind,
            "kinds": list(KIND_LABELS.items()),
            "label": KIND_LABELS[kind],
            "unit": KIND_UNITS[kind],
            "now_local": now_local,
        },
    )


@router.post("/growth/new")
async def growth_create(
    request: Request,
    kind: str = Form(...),
    value: float = Form(...),
    measured_at: str = Form(...),
    source: str = Form("home"),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if kind not in KIND_LABELS:
        raise HTTPException(status_code=400, detail="Unbekannte Metrik")

    if kind == "weight":
        if not (500 <= value <= 30000):
            raise HTTPException(status_code=400, detail="Gewicht muss 500–30000 g sein")
    elif kind == "length":
        if not (30 <= value <= 150):
            raise HTTPException(status_code=400, detail="Länge muss 30–150 cm sein")
    elif kind == "head":
        if not (25 <= value <= 60):
            raise HTTPException(status_code=400, detail="Kopfumfang muss 25–60 cm sein")

    try:
        from babytracker.routes._shared import parse_past_datetime
        dt_local = parse_past_datetime(measured_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    child = _get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)
    m = Measurement(
        child_id=child.id,
        measured_at=dt_local,
        kind=kind,
        value=value,
        source=source if source in {"home", "doctor", "hospital"} else "home",
        created_by=_get_user_id(session, user),
        notes=notes.strip() or None,
    )
    session.add(m)
    session.commit()

    return RedirectResponse(url=f"{request.scope.get('root_path', '')}/growth?kind={kind}", status_code=303)


@router.get("/growth/{measurement_id}/edit", response_class=HTMLResponse)
async def growth_edit_form(
    request: Request,
    measurement_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    from babytracker.routes._shared import now_local_iso as _now_local_iso
    child = _get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)
    entry = session.get(Measurement, measurement_id)
    if not entry or entry.child_id != child.id:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/growth", status_code=303)

    m_local = entry.measured_at
    if m_local.tzinfo is None:
        m_local = m_local.replace(tzinfo=TZ)
    return templates.TemplateResponse(
        request, "growth/new.html",
        {
            "user": user, "version": request.app.version,
            "child_name": child.name,
            "kind": entry.kind,
            "kinds": list(KIND_LABELS.items()),
            "label": KIND_LABELS[entry.kind],
            "unit": KIND_UNITS[entry.kind],
            "now_local": m_local.astimezone(TZ).strftime("%Y-%m-%dT%H:%M"),
            "now_local_max": _now_local_iso(),
            "entry": entry, "is_edit": True,
        },
    )


@router.post("/growth/{measurement_id}/edit")
async def growth_edit_save(
    request: Request,
    measurement_id: int,
    kind: str = Form(...),
    value: float = Form(...),
    measured_at: str = Form(...),
    source: str = Form("home"),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if kind not in KIND_LABELS:
        raise HTTPException(status_code=400, detail="Unbekannte Metrik")
    child = _get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)
    entry = session.get(Measurement, measurement_id)
    if not entry or entry.child_id != child.id:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/growth", status_code=303)

    if kind == "weight" and not (500 <= value <= 30000):
        raise HTTPException(status_code=400, detail="Gewicht muss 500–30000 g sein")
    if kind == "length" and not (30 <= value <= 150):
        raise HTTPException(status_code=400, detail="Länge muss 30–150 cm sein")
    if kind == "head" and not (25 <= value <= 60):
        raise HTTPException(status_code=400, detail="Kopfumfang muss 25–60 cm sein")

    from babytracker.routes._shared import parse_past_datetime
    try:
        dt_local = parse_past_datetime(measured_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    entry.kind = kind
    entry.value = value
    entry.measured_at = dt_local
    entry.source = source if source in {"home", "doctor", "hospital"} else "home"
    entry.notes = notes.strip() or None
    session.add(entry)
    session.commit()
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/growth?kind={kind}", status_code=303)


@router.post("/growth/{measurement_id}/delete")
async def growth_delete(
    request: Request,
    measurement_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    child = _get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)
    m = session.get(Measurement, measurement_id)
    kind = "weight"
    if m and m.child_id == child.id:
        kind = m.kind
        session.delete(m)
        session.commit()
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/growth?kind={kind}", status_code=303)
