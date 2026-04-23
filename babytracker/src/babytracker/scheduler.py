"""APScheduler-Job für Warnungs-Checks und (später) Owlet-Aggregation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.db import engine
from babytracker.models import Child, NotifyTarget, WarningState
from babytracker.services.daily import as_aware
from babytracker.services.ha_client import notify_mobile
from babytracker.services.warnings import is_push_enabled, run_all

log = logging.getLogger(__name__)
TZ = ZoneInfo(settings.timezone)

# Gleicher Alarm wird höchstens alle N Stunden erneut gepusht (solange durchgehend aktiv).
RENOTIFY_HOURS = 6

scheduler: AsyncIOScheduler | None = None

# Serialisiert Checks: Scheduler-Tick und manueller Trigger teilen sich den Lock,
# damit keine gleichzeitigen DB-Writes auf `warning_states` kollidieren.
_check_lock = asyncio.Lock()


async def check_warnings_job() -> None:
    async with _check_lock:
        try:
            await _check_warnings_impl()
        except Exception:
            log.exception("check_warnings_job failed")


async def _check_warnings_impl() -> None:
    now = datetime.now(TZ)
    with Session(engine) as session:
        child = session.exec(
            select(Child).where(Child.active == True).order_by(Child.id)  # noqa: E712
        ).first()
        if not child:
            log.info("Warning check skipped: no active child")
            return

        warnings_found = run_all(session, child, now)
        active_codes: set[str] = set()
        pushed_count = 0

        for w in warnings_found:
            active_codes.add(w.code)
            state = session.get(WarningState, w.code)

            # Wenn User quittiert hat → Bedingung noch da aber stumm
            if state and state.dismissed_at is not None:
                state.last_seen_at = now
                state.severity = w.severity
                state.title = w.title
                state.message = w.message
                continue

            was_inactive = state is not None and not state.active
            should_notify = False

            if not state:
                state = WarningState(
                    code=w.code,
                    child_id=child.id,
                    first_seen_at=now,
                    last_seen_at=now,
                    active=True,
                    severity=w.severity,
                    title=w.title,
                    message=w.message,
                )
                session.add(state)
                should_notify = True
            else:
                state.last_seen_at = now
                state.active = True
                state.severity = w.severity
                state.title = w.title
                state.message = w.message

                if was_inactive:
                    # Reaktivierung — Warnung war zwischenzeitlich weg
                    should_notify = True
                elif state.last_notified_at is None:
                    should_notify = True
                else:
                    last_notified = as_aware(state.last_notified_at)
                    hours = (now - last_notified).total_seconds() / 3600
                    if hours >= RENOTIFY_HOURS:
                        should_notify = True

            if should_notify and is_push_enabled(session, w.code):
                targets = session.exec(
                    select(NotifyTarget).where(NotifyTarget.enabled == True)  # noqa: E712
                ).all()
                any_ok = False
                for t in targets:
                    ok = await notify_mobile(
                        t.service_name,
                        f"Baby: {w.title}",
                        w.message,
                        critical=(w.severity == "critical"),
                    )
                    any_ok = any_ok or ok
                if any_ok:
                    state.last_notified_at = now
                    pushed_count += 1
                    log.info(
                        "Warning pushed: %s (%s) to %d target(s)",
                        w.code, w.severity, len(targets),
                    )
                elif not targets:
                    log.info("Warning %s: no enabled notify targets", w.code)

        # Inaktivieren wenn Bedingung ganz weg (auch quittierte werden dann zurückgesetzt)
        existing = session.exec(select(WarningState)).all()
        deactivated = 0
        for w_state in existing:
            if w_state.code in active_codes:
                continue
            # Bedingung ist weg: Reset aller Flags damit frischer Start möglich
            if w_state.active or w_state.dismissed_at is not None:
                w_state.active = False
                w_state.last_notified_at = None
                w_state.dismissed_at = None
                session.add(w_state)
                deactivated += 1

        session.commit()

    log.info(
        "Warning check: %d active, %d pushed, %d deactivated",
        len(warnings_found), pushed_count, deactivated,
    )


def _migrate_legacy_notify_service() -> None:
    """Überträgt ``BT_NOTIFY_SERVICE`` (Add-on-Config-Altfeld) einmalig in die DB."""
    if not settings.notify_service:
        return
    with Session(engine) as session:
        existing = session.exec(select(NotifyTarget).limit(1)).first()
        if existing:
            return
        svc = settings.notify_service
        if svc.startswith("notify."):
            svc = svc[len("notify."):]
        session.add(
            NotifyTarget(
                service_name=svc,
                label=svc.replace("mobile_app_", "").replace("_", " ").title() or svc,
                enabled=True,
            )
        )
        session.commit()
        log.info("Migrated legacy notify_service '%s' to notify_targets", svc)


def start_scheduler() -> AsyncIOScheduler:
    global scheduler
    if scheduler is not None:
        return scheduler

    _migrate_legacy_notify_service()

    from babytracker.services.reminders import (
        remind_length_late,
        remind_length_morning,
        remind_vitd_late,
        remind_vitd_morning,
        remind_weight_late,
        remind_weight_morning,
    )

    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(
        check_warnings_job, "interval", minutes=2, id="check_warnings", max_instances=1
    )

    # Tägliche Reminder 09:00 + 10:00
    scheduler.add_job(
        remind_weight_morning, CronTrigger(hour=9, minute=0, timezone=TZ),
        id="remind_weight_morning", max_instances=1,
    )
    scheduler.add_job(
        remind_weight_late, CronTrigger(hour=10, minute=0, timezone=TZ),
        id="remind_weight_late", max_instances=1,
    )
    scheduler.add_job(
        remind_vitd_morning, CronTrigger(hour=9, minute=0, timezone=TZ),
        id="remind_vitd_morning", max_instances=1,
    )
    scheduler.add_job(
        remind_vitd_late, CronTrigger(hour=10, minute=0, timezone=TZ),
        id="remind_vitd_late", max_instances=1,
    )
    # Wöchentlich Sonntags
    scheduler.add_job(
        remind_length_morning, CronTrigger(day_of_week="sun", hour=9, minute=0, timezone=TZ),
        id="remind_length_morning", max_instances=1,
    )
    scheduler.add_job(
        remind_length_late, CronTrigger(day_of_week="sun", hour=10, minute=0, timezone=TZ),
        id="remind_length_late", max_instances=1,
    )

    scheduler.start()
    log.info("Scheduler started: warnings every 2 min + daily/weekly reminders")
    return scheduler


def stop_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
