"""APScheduler-Job für Warnungs-Checks und (später) Owlet-Aggregation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.db import engine
from babytracker.models import Child, WarningState
from babytracker.models import NotifyTarget
from babytracker.services.ha_client import notify_mobile
from babytracker.services.warnings import is_push_enabled, run_all

log = logging.getLogger(__name__)
TZ = ZoneInfo(settings.timezone)

# Gleicher Alarm wird höchstens alle N Stunden erneut gepusht.
RENOTIFY_HOURS = 6

scheduler: AsyncIOScheduler | None = None


async def check_warnings_job() -> None:
    log.debug("Warning check job started")
    now = datetime.now(TZ)
    with Session(engine) as session:
        child = session.exec(
            select(Child).where(Child.active == True).order_by(Child.id)  # noqa: E712
        ).first()
        if not child:
            return

        active_codes = set()
        for w in run_all(session, child, now):
            active_codes.add(w.code)
            state = session.get(WarningState, w.code)
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
                if state.last_notified_at is None:
                    should_notify = True
                else:
                    hours = (now - state.last_notified_at).total_seconds() / 3600
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

        # Bestehende Warnungen deaktivieren, wenn sie nicht mehr im aktuellen Run aufgetaucht sind
        existing = session.exec(select(WarningState).where(WarningState.active == True)).all()  # noqa: E712
        for w_state in existing:
            if w_state.code not in active_codes:
                w_state.active = False
                session.add(w_state)

        session.commit()
    log.debug("Warning check job done")


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

    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(check_warnings_job, "interval", minutes=5, id="check_warnings", max_instances=1)
    scheduler.start()
    log.info("Scheduler started: warning checks every 5 min")
    return scheduler


def stop_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        scheduler = None
