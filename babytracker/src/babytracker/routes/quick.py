from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from babytracker.auth import CurrentUser, get_current_user

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/quick", response_class=HTMLResponse)
async def quick(request: Request, user: CurrentUser = Depends(get_current_user)):
    return templates.TemplateResponse(
        request,
        "quick.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": "Baby",
        },
    )
