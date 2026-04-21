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

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

TZ = ZoneInfo(settings.timezone)


@router.get("/setup/child", response_class=HTMLResponse)
async def setup_child_form(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    existing = session.exec(select(Child).where(Child.active == True)).first()  # noqa: E712
    now_local = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M")

    if existing:
        prefill = {
            "name": existing.name,
            "sex": existing.sex,
            "birth_at": existing.birth_at.astimezone(TZ).strftime("%Y-%m-%dT%H:%M"),
            "birth_weight_g": existing.birth_weight_g or "",
            "birth_length_cm": existing.birth_length_cm or "",
        }
    else:
        prefill = {
            "name": "",
            "sex": "f",
            "birth_at": now_local,
            "birth_weight_g": "",
            "birth_length_cm": "",
        }

    return templates.TemplateResponse(
        request,
        "setup/child.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": existing.name if existing else "Baby",
            "existing": existing,
            "prefill": prefill,
        },
    )


@router.post("/setup/child")
async def setup_child_save(
    request: Request,
    name: str = Form(...),
    sex: str = Form(...),
    birth_at: str = Form(...),
    birth_weight_g: int = Form(0),
    birth_length_cm: float = Form(0.0),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    if sex not in ("f", "m"):
        raise HTTPException(status_code=400, detail="sex muss 'f' oder 'm' sein")

    try:
        dt = datetime.fromisoformat(birth_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Ungültiges Datum: {e}")

    existing = session.exec(select(Child).where(Child.active == True)).first()  # noqa: E712

    if existing:
        existing.name = name
        existing.sex = sex
        existing.birth_at = dt
        existing.birth_weight_g = birth_weight_g or None
        existing.birth_length_cm = birth_length_cm or None
        child = existing
    else:
        child = Child(
            name=name,
            sex=sex,
            birth_at=dt,
            birth_weight_g=birth_weight_g or None,
            birth_length_cm=birth_length_cm or None,
        )
        session.add(child)
    session.flush()

    db_user = session.exec(select(User).where(User.name == user.name)).first()
    if not db_user:
        db_user = session.exec(select(User).order_by(User.id)).first()
    creator_id = db_user.id if db_user else None

    if not existing and birth_weight_g:
        session.add(
            Measurement(
                child_id=child.id,
                measured_at=dt,
                kind="weight",
                value=float(birth_weight_g),
                source="hospital",
                created_by=creator_id,
                notes="Geburtsgewicht",
            )
        )
    if not existing and birth_length_cm:
        session.add(
            Measurement(
                child_id=child.id,
                measured_at=dt,
                kind="length",
                value=float(birth_length_cm),
                source="hospital",
                created_by=creator_id,
                notes="Geburtslänge",
            )
        )

    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/growth", status_code=303)
