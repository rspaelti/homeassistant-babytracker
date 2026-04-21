from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import WarningState
from babytracker.routes._shared import TZ, get_child
from babytracker.services.daily import format_ago
from babytracker.services.warnings import run_all

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

    # Live-Check zusätzlich zu State-History
    live = run_all(session, child, datetime.now(TZ))
    history = session.exec(
        select(WarningState).order_by(WarningState.last_seen_at.desc()).limit(20)
    ).all()

    return templates.TemplateResponse(
        request,
        "warnings/index.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name,
            "live": live,
            "history": history,
            "format_ago": format_ago,
        },
    )
