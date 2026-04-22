"""Gemeinsame Helper für Routen."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.auth import CurrentUser
from babytracker.config import settings
from babytracker.models import Child, User

TZ = ZoneInfo(settings.timezone)


def get_child(session: Session) -> Child | None:
    return session.exec(
        select(Child).where(Child.active == True).order_by(Child.id)  # noqa: E712
    ).first()


def get_user_id(session: Session, user: CurrentUser) -> int | None:
    db_user = session.exec(select(User).where(User.name == user.name)).first()
    if not db_user:
        db_user = session.exec(select(User).order_by(User.id)).first()
    return db_user.id if db_user else None


def parse_local_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def parse_past_datetime(value: str, allow_future_seconds: int = 60) -> datetime:
    """Wie parse_local_datetime, wirft aber 400 wenn > jetzt (mit kleiner Karenz).

    Die Karenz fängt Uhrzeit-Drift zwischen Client und Server ab.
    """
    from fastapi import HTTPException

    dt = parse_local_datetime(value)
    now = datetime.now(TZ)
    if (dt - now).total_seconds() > allow_future_seconds:
        raise HTTPException(
            status_code=400,
            detail=f"Zeitpunkt darf nicht in der Zukunft liegen ({dt.strftime('%d.%m.%Y %H:%M')}).",
        )
    return dt


def now_local_iso() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%dT%H:%M")
