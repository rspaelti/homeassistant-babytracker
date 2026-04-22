from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import NotifyTarget, WarningState
from babytracker.routes._shared import TZ, get_child
from babytracker.services.daily import format_ago
from babytracker.scheduler import check_warnings_job
from babytracker.services.ha_client import list_mobile_app_notify_services, notify_mobile
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


def _redirect_to_warnings(request: Request) -> RedirectResponse:
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/warnings", status_code=303)


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
    session.commit()

    targets = session.exec(select(NotifyTarget).order_by(NotifyTarget.id)).all()
    # Verfügbare HA-notify-Services, die noch nicht als Target hinterlegt sind
    existing_services = {t.service_name for t in targets}
    discovered = await list_mobile_app_notify_services()
    available = [s for s in discovered if s not in existing_services]

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
            "targets": targets,
            "available_services": available,
            "ha_reachable": discovered or not existing_services,
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
    if code in RULES_BY_CODE:
        set_rule_enabled(session, code, bool(enabled))
    return _redirect_to_warnings(request)


@router.post("/warnings/rules/{code}/toggle_push")
async def toggle_push(
    request: Request,
    code: str,
    push_enabled: str = Form(""),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    if code in RULES_BY_CODE:
        set_rule_push_enabled(session, code, bool(push_enabled))
    return _redirect_to_warnings(request)


# --- Notify-Targets -----------------------------------------------------------

@router.post("/warnings/targets/add")
async def target_add(
    request: Request,
    service_name: str = Form(...),
    label: str = Form(""),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    service_name = service_name.strip()
    if service_name.startswith("notify."):
        service_name = service_name[len("notify."):]
    if not service_name:
        return _redirect_to_warnings(request)

    existing = session.exec(
        select(NotifyTarget).where(NotifyTarget.service_name == service_name)
    ).first()
    if existing:
        return _redirect_to_warnings(request)

    if not label.strip():
        label = service_name.replace("mobile_app_", "").replace("_", " ").title()

    session.add(NotifyTarget(service_name=service_name, label=label.strip(), enabled=True))
    session.commit()
    return _redirect_to_warnings(request)


@router.post("/warnings/targets/{target_id}/toggle")
async def target_toggle(
    request: Request,
    target_id: int,
    enabled: str = Form(""),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    t = session.get(NotifyTarget, target_id)
    if t:
        t.enabled = bool(enabled)
        session.add(t)
        session.commit()
    return _redirect_to_warnings(request)


@router.post("/warnings/targets/{target_id}/delete")
async def target_delete(
    request: Request,
    target_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    t = session.get(NotifyTarget, target_id)
    if t:
        session.delete(t)
        session.commit()
    return _redirect_to_warnings(request)


@router.post("/warnings/targets/{target_id}/test")
async def target_test(
    request: Request,
    target_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    t = session.get(NotifyTarget, target_id)
    if t:
        await notify_mobile(
            t.service_name,
            "Baby-Tracker: Test",
            f"Test-Notification für {t.label}. Wenn du das liest, funktioniert es.",
            critical=False,
        )
    return _redirect_to_warnings(request)


@router.post("/warnings/check_now")
async def check_now(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
):
    """Manueller Trigger: Warnungs-Scan jetzt laufen lassen inkl. Push."""
    await check_warnings_job()
    return _redirect_to_warnings(request)
