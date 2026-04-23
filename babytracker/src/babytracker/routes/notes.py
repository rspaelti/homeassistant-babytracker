from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from babytracker.auth import CurrentUser, get_current_user
from babytracker.db import get_session
from babytracker.models import Note
from babytracker.routes._shared import get_child, get_user_id, now_local_iso, parse_past_datetime

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/notes/new", response_class=HTMLResponse)
async def note_new(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    return templates.TemplateResponse(
        request,
        "notes/new.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name if child else "Baby",
            "now_local": now_local_iso(),
        },
    )


@router.post("/notes/new")
async def note_create(
    request: Request,
    logged_at: str = Form(...),
    body: str = Form(...),
    tags: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not body.strip():
        raise HTTPException(status_code=400, detail="Text erforderlich")

    try:
        dt = parse_past_datetime(logged_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")

    child = get_child(session)
    user_id = get_user_id(session, user)

    session.add(
        Note(
            child_id=child.id if child else None,
            mother_id=user_id,
            logged_at=dt,
            body=body.strip(),
            tags=tags.strip() or None,
        )
    )
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/timeline", status_code=303)


@router.get("/notes/{note_id}/edit", response_class=HTMLResponse)
async def note_edit_form(
    request: Request,
    note_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    entry = session.get(Note, note_id)
    if not entry:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/timeline", status_code=303)
    from babytracker.routes._shared import TZ as _TZ
    logged_local = entry.logged_at if entry.logged_at.tzinfo else entry.logged_at.replace(tzinfo=_TZ)
    child = get_child(session)
    return templates.TemplateResponse(
        request, "notes/new.html",
        {
            "user": user, "version": request.app.version,
            "child_name": child.name if child else "Baby",
            "now_local": logged_local.astimezone(_TZ).strftime("%Y-%m-%dT%H:%M"),
            "now_local_max": now_local_iso(),
            "entry": entry, "is_edit": True,
        },
    )


@router.post("/notes/{note_id}/edit")
async def note_edit_save(
    request: Request,
    note_id: int,
    logged_at: str = Form(...),
    body: str = Form(...),
    tags: str = Form(""),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    entry = session.get(Note, note_id)
    if not entry:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/timeline", status_code=303)
    if not body.strip():
        raise HTTPException(status_code=400, detail="Text erforderlich")
    try:
        dt = parse_past_datetime(logged_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültiges Datum")
    entry.logged_at = dt
    entry.body = body.strip()
    entry.tags = tags.strip() or None
    session.add(entry)
    session.commit()
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/timeline", status_code=303)


@router.post("/notes/{note_id}/delete")
async def note_delete(
    request: Request,
    note_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
):
    n = session.get(Note, note_id)
    if n:
        session.delete(n)
        session.commit()
    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/timeline", status_code=303)
