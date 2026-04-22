from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.config import settings
from babytracker.db import get_session
from babytracker.models import WarningState
from babytracker.routes._shared import TZ, get_child
from babytracker.services.daily import format_ago
from babytracker.services.warnings import (
    ALL_RULES,
    RULES_BY_CODE,
    all_rule_configs,
    run_all,
    set_rule_enabled,
    set_rule_push_enabled,
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/warnings", response_class=HTMLResponse)
async def warnings_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    if not child:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/setup/child", status_code=303)

    live = run_all(session, child, datetime.now(TZ))
    history = session.exec(
        select(WarningState).order_by(WarningState.last_seen_at.desc()).limit(20)
    ).all()
    configs = all_rule_configs(session)
    session.commit()  # configs wurden ggf. initial geseedet

    return templates.TemplateResponse(
        request,
        "warnings/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "live": live,
            "history": history,
            "rules": ALL_RULES,
            "configs": configs,
            "notify_service_configured": bool(settings.notify_service),
            "format_ago": format_ago,
        },
    )


@router.post("/warnings/rules/{code}/toggle")
async def toggle_rule(
    request: Request,
    code: str,
    enabled: str = Form(""),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    if code not in RULES_BY_CODE:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/warnings", status_code=303)
    set_rule_enabled(session, code, bool(enabled))
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/warnings", status_code=303)


@router.post("/warnings/rules/{code}/toggle_push")
async def toggle_push(
    request: Request,
    code: str,
    push_enabled: str = Form(""),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    if code not in RULES_BY_CODE:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/warnings", status_code=303)
    set_rule_push_enabled(session, code, bool(push_enabled))
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/warnings", status_code=303)
