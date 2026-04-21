"""Aggregate für Tagesbilanzen (Stillen, Windeln, Schlaf)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, and_, or_, select

from babytracker.config import settings
from babytracker.models import Diaper, Feeding, SleepSession

TZ = ZoneInfo(settings.timezone)


def day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=TZ)
    end = start + timedelta(days=1)
    return start, end


def as_aware(dt: datetime | None) -> datetime | None:
    """SQLite gibt tz-naive Datetimes zurück. Als lokale Zeit interpretieren."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt


@dataclass
class FeedSummary:
    count: int
    breast_min: int
    bottle_ml: int
    last_at: datetime | None


@dataclass
class DiaperSummary:
    pees: int
    stools: int
    last_at: datetime | None


@dataclass
class SleepSummary:
    total_minutes: int
    sessions: int
    active: SleepSession | None
    last_ended_at: datetime | None


def feed_summary(session: Session, child_id: int, day: date) -> FeedSummary:
    start, end = day_bounds_utc(day)
    feedings = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child_id)
        .where(Feeding.started_at >= start)
        .where(Feeding.started_at < end)
    ).all()

    breast_min = sum(
        (f.duration_left_min or 0) + (f.duration_right_min or 0) for f in feedings
    )
    bottle_ml = sum((f.bottle_taken_ml or 0) for f in feedings)

    last = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child_id)
        .order_by(Feeding.started_at.desc())
    ).first()

    return FeedSummary(
        count=len(feedings),
        breast_min=breast_min,
        bottle_ml=bottle_ml,
        last_at=as_aware(last.started_at) if last else None,
    )


def diaper_summary(session: Session, child_id: int, day: date) -> DiaperSummary:
    start, end = day_bounds_utc(day)
    diapers = session.exec(
        select(Diaper)
        .where(Diaper.child_id == child_id)
        .where(Diaper.changed_at >= start)
        .where(Diaper.changed_at < end)
    ).all()

    pees = sum(1 for d in diapers if d.pee)
    stools = sum(1 for d in diapers if d.stool)

    last = session.exec(
        select(Diaper)
        .where(Diaper.child_id == child_id)
        .order_by(Diaper.changed_at.desc())
    ).first()

    return DiaperSummary(
        pees=pees,
        stools=stools,
        last_at=as_aware(last.changed_at) if last else None,
    )


def sleep_summary(session: Session, child_id: int, day: date) -> SleepSummary:
    start, end = day_bounds_utc(day)

    sessions = session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child_id)
        .where(
            or_(
                and_(SleepSession.started_at >= start, SleepSession.started_at < end),
                and_(SleepSession.ended_at >= start, SleepSession.ended_at < end),
            )
        )
    ).all()

    total = 0
    for s in sessions:
        s_start = as_aware(s.started_at)
        s_end = as_aware(s.ended_at) or datetime.now(TZ)
        clamped_start = max(s_start, start)
        clamped_end = min(s_end, end)
        if clamped_end > clamped_start:
            total += int((clamped_end - clamped_start).total_seconds() / 60)

    active = session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child_id)
        .where(SleepSession.ended_at.is_(None))
        .order_by(SleepSession.started_at.desc())
    ).first()
    if active:
        active.started_at = as_aware(active.started_at)

    last_ended = session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child_id)
        .where(SleepSession.ended_at.is_not(None))
        .order_by(SleepSession.ended_at.desc())
    ).first()

    return SleepSummary(
        total_minutes=total,
        sessions=len(sessions),
        active=active,
        last_ended_at=as_aware(last_ended.ended_at) if last_ended else None,
    )


def format_ago(dt: datetime | None, now: datetime | None = None) -> str:
    if dt is None:
        return "–"
    now = now or datetime.now(TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    delta = now - dt
    mins = int(delta.total_seconds() / 60)
    if mins < 1:
        return "jetzt"
    if mins < 60:
        return f"vor {mins} Min."
    hours = mins // 60
    mins = mins % 60
    if hours < 24:
        if mins:
            return f"vor {hours}h {mins:02d}"
        return f"vor {hours}h"
    days = hours // 24
    return f"vor {days}d"


def format_duration(minutes: int) -> str:
    if minutes <= 0:
        return "–"
    h = minutes // 60
    m = minutes % 60
    if h:
        return f"{h}h {m:02d}"
    return f"{m} Min."
