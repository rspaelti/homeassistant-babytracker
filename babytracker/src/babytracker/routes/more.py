from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import WarningState

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/more", response_class=HTMLResponse)
async def more_index(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    active_count = len(
        session.exec(select(WarningState).where(WarningState.active == True)).all()  # noqa: E712
    )
    return templates.TemplateResponse(
        request,
        "more.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": "Baby",
            "active_warning_count": active_count,
        },
    )
