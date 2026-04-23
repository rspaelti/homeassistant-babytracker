"""Zeitbasierte Reminder: Gewicht, Länge/Kopfumfang, Vitamin D.

Läuft via APScheduler-Cron-Jobs und pusht direkt an NotifyTargets
(kein WarningState, weil stateless Erinnerung).
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.db import engine
from babytracker.models import Child, Measurement, Medication, NotifyTarget
from babytracker.services.daily import day_bounds_utc
from babytracker.services.ha_client import notify_mobile
from babytracker.services.warnings import is_enabled, is_push_enabled

log = logging.getLogger(__name__)
TZ = ZoneInfo(settings.timezone)


# Reminder-Codes — werden als WarningRules registriert (siehe warnings.py)
CODE_WEIGHT_MORNING = "reminder_weight_morning"
CODE_WEIGHT_LATE = "reminder_weight_late"
CODE_VITD_MORNING = "reminder_vitd_morning"
CODE_VITD_LATE = "reminder_vitd_late"
CODE_LENGTH_MORNING = "reminder_length_morning"
CODE_LENGTH_LATE = "reminder_length_late"


def _get_child(session: Session) -> Child | None:
    return session.exec(
        select(Child).where(Child.active == True).order_by(Child.id)  # noqa: E712
    ).first()


def _measured_today(session: Session, child_id: int, kinds: list[str]) -> bool:
    today = datetime.now(TZ).date()
    start, end = day_bounds_utc(today)
    q = session.exec(
        select(Measurement)
        .where(
            Measurement.child_id == child_id,
            Measurement.kind.in_(kinds),  # type: ignore[attr-defined]
            Measurement.measured_at >= start,
            Measurement.measured_at < end,
        )
        .limit(1)
    ).first()
    return q is not None


def _vit_d_given_today(session: Session, child_id: int) -> bool:
    today = datetime.now(TZ).date()
    start, end = day_bounds_utc(today)
    q = session.exec(
        select(Medication)
        .where(
            Medication.child_id == child_id,
            Medication.med_name == "vitamin_d",
            Medication.given_at >= start,
            Medication.given_at < end,
        )
        .limit(1)
    ).first()
    return q is not None


async def _push_reminder(code: str, title: str, message: str) -> None:
    with Session(engine) as session:
        if not is_enabled(session, code):
            log.info("Reminder %s: disabled", code)
            return
        push_ok = is_push_enabled(session, code)
        targets = session.exec(
            select(NotifyTarget).where(NotifyTarget.enabled == True)  # noqa: E712
        ).all()
        session.commit()

    if not push_ok:
        log.info("Reminder %s: push disabled", code)
        return
    if not targets:
        log.info("Reminder %s: no targets", code)
        return

    count = 0
    for t in targets:
        ok = await notify_mobile(t.service_name, f"Baby: {title}", message, critical=False)
        if ok:
            count += 1
    log.info("Reminder %s pushed to %d/%d targets", code, count, len(targets))


# --- Job-Funktionen ----------------------------------------------------------

async def remind_weight_morning() -> None:
    await _push_reminder(
        CODE_WEIGHT_MORNING,
        "⚖️ Zeit fürs Wiegen",
        "Bitte heute das Gewicht eintragen.",
    )


async def remind_weight_late() -> None:
    with Session(engine) as session:
        child = _get_child(session)
        if not child:
            return
        if _measured_today(session, child.id, ["weight"]):
            log.info("Reminder weight_late: already done today")
            return
    await _push_reminder(
        CODE_WEIGHT_LATE,
        "⚖️ Gewicht noch nicht erfasst",
        "Heute um 09:00 war die Erinnerung — bitte Gewicht nachtragen.",
    )


async def remind_vitd_morning() -> None:
    await _push_reminder(
        CODE_VITD_MORNING,
        "💊 Vitamin D geben",
        "Tägliche Vitamin-D-Gabe nicht vergessen.",
    )


async def remind_vitd_late() -> None:
    with Session(engine) as session:
        child = _get_child(session)
        if not child:
            return
        if _vit_d_given_today(session, child.id):
            log.info("Reminder vitd_late: already given today")
            return
    await _push_reminder(
        CODE_VITD_LATE,
        "💊 Vitamin D fehlt noch",
        "Vitamin D heute noch nicht verabreicht — bitte nachholen.",
    )


async def remind_length_morning() -> None:
    """Sonntags Länge + Kopfumfang."""
    await _push_reminder(
        CODE_LENGTH_MORNING,
        "📏 Länge + Kopfumfang messen",
        "Sonntag 09:00 — bitte Länge und Kopfumfang messen und eintragen.",
    )


async def remind_length_late() -> None:
    with Session(engine) as session:
        child = _get_child(session)
        if not child:
            return
        if _measured_today(session, child.id, ["length", "head"]):
            log.info("Reminder length_late: already done today")
            return
    await _push_reminder(
        CODE_LENGTH_LATE,
        "📏 Länge/Kopf noch fehlend",
        "Sonntags-Messung Länge + Kopfumfang bitte nachtragen.",
    )
