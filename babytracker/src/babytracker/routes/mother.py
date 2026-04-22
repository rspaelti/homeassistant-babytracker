from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import Child, MotherLog, User
from babytracker.routes._shared import TZ, get_child, get_user_id, now_local_iso, parse_local_datetime
from babytracker.services.daily import as_aware, format_ago
from babytracker.services.mother import (
    EPDS_QUESTIONS,
    compute_clexane_end_date,
    epds_interpret,
    overview,
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

WOUND_STATUS = [
    ("ok", "Unauffällig"),
    ("red", "Gerötet"),
    ("wet", "Nässt"),
    ("secretion_yellow", "Gelbes Sekret"),
    ("secretion_green", "Grünes Sekret"),
    ("bloody", "Blutig"),
]
LOCHIA_COLOR = [
    ("red", "Rot"),
    ("brown", "Braun"),
    ("yellow", "Gelblich"),
    ("white", "Weiss"),
]
LOCHIA_AMOUNT = [
    ("heavy", "Stark"),
    ("normal", "Normal"),
    ("light", "Wenig"),
]
THROMBOSIS_RESULT = [
    ("ok", "Unauffällig"),
    ("swelling", "Schwellung"),
    ("redness", "Rötung"),
    ("pain", "Schmerz"),
]
MOOD_SCALE = [
    (5, "Sehr gut", "😄"),
    (4, "Gut", "🙂"),
    (3, "Neutral", "😐"),
    (2, "Schlecht", "😔"),
    (1, "Sehr schlecht", "😢"),
]


def _mother_id(session: Session, user: CurrentUser) -> int:
    uid = get_user_id(session, user)
    if uid is not None:
        return uid
    # Fallback: leerer User-Bestand → Parent anlegen, damit FK zieht
    parent = User(name=user.name or "Parent", role="parent")
    session.add(parent)
    session.flush()
    return parent.id


def _redirect_mother(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/mother", status_code=303)


def _ctx_base(request: Request, user: CurrentUser, child: Child | None) -> dict:
    return {
        "user": user,
        "version": request.app.version,
        "child_name": child.name if child else "Baby",
        "now_local": now_local_iso(),
    }


@router.get("/mother", response_class=HTMLResponse)
async def mother_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    ov = overview(session, child.birth_at if child else None)
    clexane_end = compute_clexane_end_date(child.birth_at) if child else None

    recent = session.exec(
        select(MotherLog).order_by(MotherLog.logged_at.desc()).limit(15)
    ).all()

    return templates.TemplateResponse(
        request,
        "mother/index.html",
        {
            **_ctx_base(request, user, child),
            "ov": ov,
            "clexane_end": clexane_end,
            "recent": recent,
            "format_ago": format_ago,
        },
    )


# --- Clexane ------------------------------------------------------------------

@router.post("/mother/clexane/quick")
async def clexane_quick(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=datetime.now(TZ),
            category="clexane",
            value_num=60.0,
            value_text="60 mg s.c.",
        )
    )
    session.commit()
    return _redirect_mother(request)


@router.get("/mother/clexane/new", response_class=HTMLResponse)
async def clexane_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    return templates.TemplateResponse(
        request,
        "mother/clexane_new.html",
        _ctx_base(request, user, child),
    )


@router.post("/mother/clexane/new")
async def clexane_create(
    request: Request,
    logged_at: str = Form(...),
    dose_mg: float = Form(60.0),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    dt = parse_local_datetime(logged_at)
    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=dt,
            category="clexane",
            value_num=dose_mg,
            value_text=f"{dose_mg:.0f} mg s.c.",
            notes=notes.strip() or None,
        )
    )
    session.commit()
    return _redirect_mother(request)


# --- Thrombose-Check ----------------------------------------------------------

@router.get("/mother/thrombosis/new", response_class=HTMLResponse)
async def thrombosis_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    return templates.TemplateResponse(
        request,
        "mother/thrombosis_new.html",
        {**_ctx_base(request, user, child), "results": THROMBOSIS_RESULT},
    )


@router.post("/mother/thrombosis/new")
async def thrombosis_create(
    request: Request,
    logged_at: str = Form(...),
    left: str = Form("ok"),
    right: str = Form("ok"),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    dt = parse_local_datetime(logged_at)
    if left not in dict(THROMBOSIS_RESULT) or right not in dict(THROMBOSIS_RESULT):
        raise HTTPException(status_code=400, detail="Ungültiger Wert")
    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=dt,
            category="thrombosis_check",
            value_text=f"L: {left}, R: {right}",
            notes=notes.strip() or None,
        )
    )
    session.commit()
    return _redirect_mother(request)


# --- Wunde --------------------------------------------------------------------

@router.get("/mother/wound/new", response_class=HTMLResponse)
async def wound_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    return templates.TemplateResponse(
        request,
        "mother/wound_new.html",
        {**_ctx_base(request, user, child), "wound_status": WOUND_STATUS},
    )


@router.post("/mother/wound/new")
async def wound_create(
    request: Request,
    logged_at: str = Form(...),
    status: str = Form("ok"),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if status not in dict(WOUND_STATUS):
        raise HTTPException(status_code=400, detail="Ungültiger Status")
    dt = parse_local_datetime(logged_at)
    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=dt,
            category="wound",
            value_text=status,
            notes=notes.strip() or None,
        )
    )
    session.commit()
    return _redirect_mother(request)


# --- Blutdruck + Puls ---------------------------------------------------------

@router.get("/mother/bp/new", response_class=HTMLResponse)
async def bp_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    return templates.TemplateResponse(
        request,
        "mother/bp_new.html",
        _ctx_base(request, user, child),
    )


@router.post("/mother/bp/new")
async def bp_create(
    request: Request,
    logged_at: str = Form(...),
    systolic: int = Form(...),
    diastolic: int = Form(...),
    pulse: int = Form(0),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not (70 <= systolic <= 220) or not (40 <= diastolic <= 140):
        raise HTTPException(status_code=400, detail="Blutdruckwerte unrealistisch")
    if pulse and not (30 <= pulse <= 220):
        raise HTTPException(status_code=400, detail="Puls unrealistisch")
    dt = parse_local_datetime(logged_at)
    payload = {"systolic": systolic, "diastolic": diastolic}
    if pulse:
        payload["pulse"] = pulse
    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=dt,
            category="bp",
            value_num=float(systolic),
            value_text=json.dumps(payload),
            notes=notes.strip() or None,
        )
    )
    session.commit()
    return _redirect_mother(request)


# --- EPDS ---------------------------------------------------------------------

@router.get("/mother/epds", response_class=HTMLResponse)
async def epds_form(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    history = session.exec(
        select(MotherLog)
        .where(MotherLog.category == "epds")
        .order_by(MotherLog.logged_at.desc())
    ).all()

    # Interpretationen für Historie
    history_with_interp = []
    for h in history:
        if h.value_num is not None:
            level, msg = epds_interpret(int(h.value_num))
            history_with_interp.append((h, level, msg))

    return templates.TemplateResponse(
        request,
        "mother/epds.html",
        {
            **_ctx_base(request, user, child),
            "questions": EPDS_QUESTIONS,
            "history": history_with_interp,
            "format_ago": format_ago,
        },
    )


@router.post("/mother/epds")
async def epds_submit(
    request: Request,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    form = await request.form()
    answers: list[int] = []
    for i in range(len(EPDS_QUESTIONS)):
        raw = form.get(f"q{i}")
        if raw is None:
            raise HTTPException(status_code=400, detail=f"Frage {i + 1} nicht beantwortet")
        try:
            val = int(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Ungültige Antwort bei Frage {i + 1}")
        if not (0 <= val <= 3):
            raise HTTPException(status_code=400, detail=f"Antwort {i + 1} ausser Bereich")
        answers.append(val)

    score = sum(answers)
    level, msg = epds_interpret(score)
    now = datetime.now(TZ)

    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=now,
            category="epds",
            value_num=float(score),
            value_text=json.dumps({"answers": answers, "level": level}),
            notes=msg,
        )
    )
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/mother/epds", status_code=303)


# --- Stimmung -----------------------------------------------------------------

@router.post("/mother/mood/quick")
async def mood_quick(
    request: Request,
    score: int = Form(...),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not (1 <= score <= 5):
        raise HTTPException(status_code=400, detail="Score 1–5")
    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=datetime.now(TZ),
            category="mood",
            value_num=float(score),
        )
    )
    session.commit()
    return _redirect_mother(request)


# --- Lochien ------------------------------------------------------------------

@router.get("/mother/lochia/new", response_class=HTMLResponse)
async def lochia_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    return templates.TemplateResponse(
        request,
        "mother/lochia_new.html",
        {
            **_ctx_base(request, user, child),
            "colors": LOCHIA_COLOR,
            "amounts": LOCHIA_AMOUNT,
        },
    )


@router.post("/mother/lochia/new")
async def lochia_create(
    request: Request,
    logged_at: str = Form(...),
    color: str = Form("red"),
    amount: str = Form("normal"),
    notes: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if color not in dict(LOCHIA_COLOR) or amount not in dict(LOCHIA_AMOUNT):
        raise HTTPException(status_code=400, detail="Ungültiger Wert")
    dt = parse_local_datetime(logged_at)
    session.add(
        MotherLog(
            mother_id=_mother_id(session, user),
            logged_at=dt,
            category="lochia",
            value_text=f"{color}/{amount}",
            notes=notes.strip() or None,
        )
    )
    session.commit()
    return _redirect_mother(request)


# --- Delete -------------------------------------------------------------------

@router.post("/mother/{log_id}/delete")
async def mother_delete(
    request: Request,
    log_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    m = session.get(MotherLog, log_id)
    if m:
        session.delete(m)
        session.commit()
    return _redirect_mother(request)
