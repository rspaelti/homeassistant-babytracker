"""Journal/Tagebuch-Routen mit Foto-Upload."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from babytracker.auth import CurrentUser, get_current_user
from babytracker.config import settings
from babytracker.db import get_session
from babytracker.models import JournalEntry, Photo
from babytracker.routes._shared import (
    TZ,
    get_child,
    get_user_id,
    now_local_iso,
    parse_local_datetime,
)
from babytracker.services import photos as photo_service
from babytracker.services.markdown_render import render as render_markdown

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

LINKED_TABLE = "journal_entries"


def _parse_tags(raw: str) -> str | None:
    """Kommagetrennt → JSON-Liste-String, leer → None."""
    if not raw or not raw.strip():
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        return None
    return json.dumps(parts, ensure_ascii=False)


def _format_tags(stored: str | None) -> list[str]:
    if not stored:
        return []
    try:
        data = json.loads(stored)
        if isinstance(data, list):
            return [str(t) for t in data]
    except (ValueError, TypeError):
        return []
    return []


def _entry_photos(session: Session, entry_id: int) -> list[Photo]:
    return list(
        session.exec(
            select(Photo)
            .where(Photo.linked_table == LINKED_TABLE, Photo.linked_id == entry_id)
            .order_by(Photo.taken_at)
        )
    )


def _to_local(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


@router.get("/journal", response_class=HTMLResponse)
async def journal_list(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    entries = list(
        session.exec(
            select(JournalEntry)
            .where(JournalEntry.deleted_at.is_(None))
            .order_by(JournalEntry.happened_at.desc())
        )
    )

    cards = []
    for e in entries:
        cover = session.exec(
            select(Photo)
            .where(Photo.linked_table == LINKED_TABLE, Photo.linked_id == e.id)
            .order_by(Photo.taken_at)
            .limit(1)
        ).first()
        photo_count = len(
            session.exec(
                select(Photo.id)
                .where(Photo.linked_table == LINKED_TABLE, Photo.linked_id == e.id)
            ).all()
        )
        cards.append(
            {
                "entry": e,
                "happened_local": _to_local(e.happened_at),
                "tags": _format_tags(e.tags),
                "cover": cover,
                "photo_count": photo_count,
            }
        )

    return templates.TemplateResponse(
        request,
        "journal/list.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name if child else "Baby",
            "cards": cards,
        },
    )


@router.get("/journal/new", response_class=HTMLResponse)
async def journal_new_form(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    child = get_child(session)
    return templates.TemplateResponse(
        request,
        "journal/edit.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name if child else "Baby",
            "is_edit": False,
            "entry": None,
            "tags_str": "",
            "happened_local": now_local_iso(),
            "now_local_max": now_local_iso(),
            "photos": [],
        },
    )


@router.post("/journal/new")
async def journal_create(
    request: Request,
    title: str = Form(...),
    happened_at: str = Form(...),
    body: str = Form(""),
    mood: str = Form(""),
    location: str = Form(""),
    tags: str = Form(""),
    visibility: str = Form("family"),
    photos: list[UploadFile] = File(default_factory=list),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not title.strip():
        raise HTTPException(status_code=400, detail="Titel erforderlich")
    try:
        happened_dt = parse_local_datetime(happened_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiges Datum") from exc

    child = get_child(session)
    user_id = get_user_id(session, user)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Kein Benutzer in DB. Bitte zuerst Setup ausführen.")

    entry = JournalEntry(
        child_id=child.id if child else None,
        author_user_id=user_id,
        happened_at=happened_dt,
        title=title.strip()[:200],
        body=body or "",
        mood=mood.strip() or None,
        location=location.strip()[:128] or None,
        tags=_parse_tags(tags),
        visibility=visibility if visibility in ("family", "parents_only") else "family",
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)

    saved_photos: list[Photo] = []
    for upload in photos:
        if not upload or not upload.filename:
            continue
        photo = await photo_service.save_upload(
            upload,
            linked_table=LINKED_TABLE,
            linked_id=entry.id,
            uploader_user_id=user_id,
            visibility=entry.visibility,
        )
        session.add(photo)
        saved_photos.append(photo)
    if saved_photos:
        session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/journal/{entry.id}", status_code=303)


@router.get("/journal/{entry_id}", response_class=HTMLResponse)
async def journal_detail(
    request: Request,
    entry_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    entry = session.get(JournalEntry, entry_id)
    if not entry or entry.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    child = get_child(session)
    photos = _entry_photos(session, entry.id)

    return templates.TemplateResponse(
        request,
        "journal/detail.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name if child else "Baby",
            "entry": entry,
            "happened_local": _to_local(entry.happened_at),
            "body_html": render_markdown(entry.body),
            "tags": _format_tags(entry.tags),
            "photos": photos,
        },
    )


@router.get("/journal/{entry_id}/edit", response_class=HTMLResponse)
async def journal_edit_form(
    request: Request,
    entry_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    entry = session.get(JournalEntry, entry_id)
    if not entry or entry.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    child = get_child(session)
    photos = _entry_photos(session, entry.id)

    happened_local = _to_local(entry.happened_at)
    return templates.TemplateResponse(
        request,
        "journal/edit.html",
        {
            "user": user,
            "version": request.app.version,
            "child_name": child.name if child else "Baby",
            "is_edit": True,
            "entry": entry,
            "tags_str": ", ".join(_format_tags(entry.tags)),
            "happened_local": happened_local.strftime("%Y-%m-%dT%H:%M") if happened_local else now_local_iso(),
            "now_local_max": now_local_iso(),
            "photos": photos,
        },
    )


@router.post("/journal/{entry_id}/edit")
async def journal_update(
    request: Request,
    entry_id: int,
    title: str = Form(...),
    happened_at: str = Form(...),
    body: str = Form(""),
    mood: str = Form(""),
    location: str = Form(""),
    tags: str = Form(""),
    visibility: str = Form("family"),
    photos: list[UploadFile] = File(default_factory=list),
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    entry = session.get(JournalEntry, entry_id)
    if not entry or entry.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
    if not title.strip():
        raise HTTPException(status_code=400, detail="Titel erforderlich")
    try:
        happened_dt = parse_local_datetime(happened_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungültiges Datum") from exc

    user_id = get_user_id(session, user)

    entry.title = title.strip()[:200]
    entry.happened_at = happened_dt
    entry.body = body or ""
    entry.mood = mood.strip() or None
    entry.location = location.strip()[:128] or None
    entry.tags = _parse_tags(tags)
    entry.visibility = visibility if visibility in ("family", "parents_only") else "family"
    session.add(entry)
    session.commit()

    saved = False
    for upload in photos:
        if not upload or not upload.filename:
            continue
        photo = await photo_service.save_upload(
            upload,
            linked_table=LINKED_TABLE,
            linked_id=entry.id,
            uploader_user_id=user_id,
            visibility=entry.visibility,
        )
        session.add(photo)
        saved = True
    if saved:
        session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/journal/{entry.id}", status_code=303)


@router.post("/journal/{entry_id}/delete")
async def journal_delete(
    request: Request,
    entry_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    entry = session.get(JournalEntry, entry_id)
    if not entry:
        root = request.scope.get("root_path", "")
        return RedirectResponse(url=f"{root}/journal", status_code=303)

    for photo in _entry_photos(session, entry.id):
        photo_service.delete_photo_files(photo)
        session.delete(photo)

    session.delete(entry)
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}/journal", status_code=303)


@router.post("/photos/{photo_id}/delete")
async def photo_delete(
    request: Request,
    photo_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    photo = session.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Foto nicht gefunden")
    redirect_target = "/journal"
    if photo.linked_table == LINKED_TABLE and photo.linked_id:
        redirect_target = f"/journal/{photo.linked_id}/edit"

    photo_service.delete_photo_files(photo)
    session.delete(photo)
    session.commit()

    root = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{root}{redirect_target}", status_code=303)


@router.get("/photos/{photo_id}")
async def photo_serve_display(
    photo_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return _serve_variant(session, photo_id, user, variant="display")


@router.get("/photos/{photo_id}/thumb")
async def photo_serve_thumb(
    photo_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return _serve_variant(session, photo_id, user, variant="thumb")


@router.get("/photos/{photo_id}/original")
async def photo_serve_original(
    photo_id: int,
    user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return _serve_variant(session, photo_id, user, variant="original", as_attachment=True)


def _serve_variant(
    session: Session,
    photo_id: int,
    user: CurrentUser,
    variant: str,
    as_attachment: bool = False,
):
    photo = session.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Foto nicht gefunden")
    if photo.visibility == "parents_only" and user.role != "parent":
        raise HTTPException(status_code=403, detail="Kein Zugriff")

    rel = {
        "display": photo.rel_path,
        "thumb": photo.thumb_path or photo.rel_path,
        "original": photo.original_path or photo.rel_path,
    }.get(variant)
    if not rel:
        raise HTTPException(status_code=404, detail="Variante nicht verfügbar")

    abs_path = Path(settings.photos_dir) / rel
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Foto-Datei fehlt auf Disk")

    media_type = "image/jpeg"
    if variant == "original":
        media_type = photo.mime or "image/jpeg"

    headers: dict[str, str] = {}
    if as_attachment:
        suffix = abs_path.suffix or ".jpg"
        headers["Content-Disposition"] = f'attachment; filename="photo-{photo.id}{suffix}"'

    return FileResponse(abs_path, media_type=media_type, headers=headers)
