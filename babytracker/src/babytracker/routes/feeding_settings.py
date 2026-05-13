"""Settings-Page für die Stillen-ml/min-Schätzung pro Altersphase."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import FeedingSettings

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


def _load_or_create(session: Session) -> FeedingSettings:
    cfg = session.get(FeedingSettings, 1)
    if cfg is None:
        cfg = FeedingSettings(id=1)
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


@router.get("/settings/feeding", response_class=HTMLResponse)
async def feeding_settings_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    cfg = _load_or_create(session)
    return templates.TemplateResponse(
        request,
        "settings/feeding.html",
        {
            "user": user,
            "version": request.app.version,
            "cfg": cfg,
        },
    )


@router.post("/settings/feeding")
async def feeding_settings_save(
    request: Request,
    phase1_max_day: int = Form(...),
    phase1_ml_per_min: float = Form(...),
    phase2_max_day: int = Form(...),
    phase2_ml_per_min: float = Form(...),
    phase3_max_day: int = Form(...),
    phase3_ml_per_min: float = Form(...),
    phase4_ml_per_min: float = Form(...),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Plausibilität: aufsteigende Tages-Schwellen, positive ml-Werte
    if not (1 <= phase1_max_day < phase2_max_day < phase3_max_day <= 365):
        raise HTTPException(400, "Tages-Schwellen müssen aufsteigend sein (1 ≤ Phase1 < Phase2 < Phase3 ≤ 365)")
    for v in (phase1_ml_per_min, phase2_ml_per_min, phase3_ml_per_min, phase4_ml_per_min):
        if v < 0 or v > 20:
            raise HTTPException(400, "ml/min muss zwischen 0 und 20 liegen")

    cfg = _load_or_create(session)
    cfg.phase1_max_day = phase1_max_day
    cfg.phase1_ml_per_min = phase1_ml_per_min
    cfg.phase2_max_day = phase2_max_day
    cfg.phase2_ml_per_min = phase2_ml_per_min
    cfg.phase3_max_day = phase3_max_day
    cfg.phase3_ml_per_min = phase3_ml_per_min
    cfg.phase4_ml_per_min = phase4_ml_per_min
    session.add(cfg)
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/settings/feeding?saved=1", status_code=303)


@router.post("/settings/feeding/reset")
async def feeding_settings_reset(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    cfg = _load_or_create(session)
    defaults = FeedingSettings()
    cfg.phase1_max_day = defaults.phase1_max_day
    cfg.phase1_ml_per_min = defaults.phase1_ml_per_min
    cfg.phase2_max_day = defaults.phase2_max_day
    cfg.phase2_ml_per_min = defaults.phase2_ml_per_min
    cfg.phase3_max_day = defaults.phase3_max_day
    cfg.phase3_ml_per_min = defaults.phase3_ml_per_min
    cfg.phase4_ml_per_min = defaults.phase4_ml_per_min
    session.add(cfg)
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/settings/feeding?saved=1", status_code=303)
