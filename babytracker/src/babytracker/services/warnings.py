"""Warnungs-Engine mit Check-Regeln.

Regeln:
- weight_loss_10: Gewichtsverlust >10% vom Geburtsgewicht in ersten 14 Tagen
- fever: Temperatur über altersabhängiger Schwelle
- low_pees: <6 Pipi ab Tag 5 (nur aktiv Tag 5+)
- no_feed_4h: Letzte Mahlzeit >4h her (nur tagsüber 7–22 Uhr)
- percentile_jump: Z-Score-Sprung zwischen zwei letzten Messungen >2
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.models import Child, Diaper, Feeding, Measurement, Vital
from babytracker.services.daily import as_aware, day_bounds_utc, diaper_summary
from babytracker.services.who_lms import evaluate

TZ = ZoneInfo(settings.timezone)


@dataclass
class WarningItem:
    code: str
    severity: str  # info / warn / critical
    title: str
    message: str
    context: dict


def _age_days(child: Child, now: datetime) -> int:
    return int((now - as_aware(child.birth_at)).total_seconds() / 86400)


def _fever_threshold(age_days: int) -> float:
    # Kinderarzt-Empfehlung: <3 Monate → ab 38.0 °C sofort Arzt/Notfall.
    if age_days < 90:
        return 38.0
    if age_days < 180:
        return 38.0
    return 38.5


def check_weight_loss(session: Session, child: Child, now: datetime) -> WarningItem | None:
    if not child.birth_weight_g:
        return None
    age = _age_days(child, now)
    if age < 1 or age > 14:
        return None
    latest = session.exec(
        select(Measurement)
        .where(Measurement.child_id == child.id, Measurement.kind == "weight")
        .order_by(Measurement.measured_at.desc())
    ).first()
    if not latest:
        return None
    if latest.value >= child.birth_weight_g:
        return None
    loss_pct = (child.birth_weight_g - latest.value) / child.birth_weight_g * 100
    if loss_pct > 10:
        return WarningItem(
            code="weight_loss_10",
            severity="critical",
            title="Gewichtsverlust >10 %",
            message=f"{latest.value:.0f} g ist {loss_pct:.1f} % unter Geburtsgewicht. Stillberatung / Arzt kontaktieren.",
            context={"loss_pct": round(loss_pct, 1), "weight_g": int(latest.value)},
        )
    return None


def check_fever(session: Session, child: Child, now: datetime) -> WarningItem | None:
    age = _age_days(child, now)
    th = _fever_threshold(age)
    since = now - timedelta(hours=6)
    latest = session.exec(
        select(Vital)
        .where(Vital.child_id == child.id, Vital.kind == "temp_body")
        .where(Vital.measured_at >= since)
        .order_by(Vital.measured_at.desc())
    ).first()
    if not latest:
        return None
    if latest.value >= th:
        return WarningItem(
            code="fever",
            severity="critical",
            title=f"Fieber: {latest.value:.1f} °C",
            message=f"Schwelle für Alter {age} Tage: {th} °C. Arzt kontaktieren.",
            context={"temp": latest.value, "threshold": th, "age_days": age},
        )
    return None


def check_low_pees(session: Session, child: Child, now: datetime) -> WarningItem | None:
    age = _age_days(child, now)
    if age < 5:
        return None
    today = now.date()
    # Nur abends warnen (nach 18:00), sonst zu früh
    if now.hour < 18:
        return None
    s = diaper_summary(session, child.id, today)
    if s.pees < 6:
        return WarningItem(
            code="low_pees",
            severity="warn",
            title=f"Nur {s.pees} Pipi heute",
            message="Ab Tag 5 sind 6+ Pipi/Tag erwartet. Falls morgen wieder so: Hebamme/Arzt kontaktieren.",
            context={"pees": s.pees, "date": today.isoformat()},
        )
    return None


def check_no_feed(session: Session, child: Child, now: datetime) -> WarningItem | None:
    # Nur tagsüber 7–22 Uhr
    if now.hour < 7 or now.hour >= 22:
        return None
    latest = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .order_by(Feeding.started_at.desc())
    ).first()
    if not latest:
        return None
    last_at = as_aware(latest.started_at)
    hours = (now - last_at).total_seconds() / 3600
    if hours >= 4:
        return WarningItem(
            code="no_feed_4h",
            severity="warn",
            title=f"Seit {hours:.1f}h keine Mahlzeit",
            message="Letzte Stillzeit/Flasche ist über 4 Stunden her.",
            context={"hours": round(hours, 1), "last_at": last_at.isoformat()},
        )
    return None


def check_percentile_jump(session: Session, child: Child, now: datetime) -> WarningItem | None:
    measurements = session.exec(
        select(Measurement)
        .where(Measurement.child_id == child.id, Measurement.kind == "weight")
        .order_by(Measurement.measured_at.desc())
        .limit(2)
    ).all()
    if len(measurements) < 2:
        return None
    latest, prev = measurements[0], measurements[1]
    age_latest = (as_aware(latest.measured_at) - as_aware(child.birth_at)).total_seconds() / 86400
    age_prev = (as_aware(prev.measured_at) - as_aware(child.birth_at)).total_seconds() / 86400
    try:
        z1, _ = evaluate("weight", child.sex, age_latest, latest.value / 1000)
        z2, _ = evaluate("weight", child.sex, age_prev, prev.value / 1000)
    except Exception:
        return None
    delta = abs(z1 - z2)
    if delta > 2:
        return WarningItem(
            code="percentile_jump",
            severity="warn",
            title=f"Gewichts-Perzentilen-Sprung (ΔZ {delta:.2f})",
            message="Grösserer Sprung im Gewichtsverlauf. Mit Kinderarzt besprechen.",
            context={"z_latest": round(z1, 2), "z_prev": round(z2, 2), "delta": round(delta, 2)},
        )
    return None


ALL_CHECKS = [
    check_weight_loss,
    check_fever,
    check_low_pees,
    check_no_feed,
    check_percentile_jump,
]


def run_all(session: Session, child: Child, now: datetime | None = None) -> list[WarningItem]:
    now = now or datetime.now(TZ)
    results: list[WarningItem] = []
    for check in ALL_CHECKS:
        try:
            w = check(session, child, now)
            if w:
                results.append(w)
        except Exception:
            continue
    return results
