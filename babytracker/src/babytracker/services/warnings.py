"""Warnungs-Engine mit konfigurierbaren Regeln.

Regeln werden als WarningRule-Objekte registriert. Jede Regel hat einen Code,
Label, Beschreibung, Default-Severity und eine Check-Funktion. Jede Regel kann
über WarningRuleConfig individuell aktiviert/deaktiviert + push-gesteuert werden.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.models import (
    Child,
    Feeding,
    Measurement,
    Vital,
    WarningRuleConfig,
)
from babytracker.services.daily import as_aware, diaper_summary
from babytracker.services.who_lms import evaluate

TZ = ZoneInfo(settings.timezone)


@dataclass
class WarningItem:
    code: str
    severity: str
    title: str
    message: str
    context: dict = field(default_factory=dict)


# --- einzelne Checks ----------------------------------------------------------

def _age_days(child: Child, now: datetime) -> int:
    return int((now - as_aware(child.birth_at)).total_seconds() / 86400)


def _fever_threshold(age_days: int) -> float:
    # Kinderarzt-Empfehlung: <3 Monate → ab 38.0 °C sofort Arzt/Notfall
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
    if not latest or latest.value >= child.birth_weight_g:
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
    if not latest or latest.value < th:
        return None
    return WarningItem(
        code="fever",
        severity="critical",
        title=f"Fieber: {latest.value:.1f} °C",
        message=f"Schwelle für Alter {age} Tage: {th} °C. Arzt / Notfall.",
        context={"temp": latest.value, "threshold": th, "age_days": age},
    )


def check_low_pees(session: Session, child: Child, now: datetime) -> WarningItem | None:
    age = _age_days(child, now)
    if age < 5 or now.hour < 18:
        return None
    s = diaper_summary(session, child.id, now.date())
    if s.pees >= 6:
        return None
    return WarningItem(
        code="low_pees",
        severity="warn",
        title=f"Nur {s.pees} Pipi heute",
        message="Ab Tag 5 sind 6+ Pipi/Tag erwartet. Falls morgen wieder so: Hebamme/Arzt kontaktieren.",
        context={"pees": s.pees, "date": now.date().isoformat()},
    )


def check_no_feed(session: Session, child: Child, now: datetime) -> WarningItem | None:
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
    if hours < 4:
        return None
    return WarningItem(
        code="no_feed_4h",
        severity="warn",
        title=f"Seit {hours:.1f}h keine Mahlzeit",
        message="Letzte Stillzeit/Flasche ist über 4 Stunden her.",
        context={"hours": round(hours, 1), "last_at": last_at.isoformat()},
    )


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
    if delta <= 2:
        return None
    return WarningItem(
        code="percentile_jump",
        severity="warn",
        title=f"Gewichts-Perzentilen-Sprung (ΔZ {delta:.2f})",
        message="Grösserer Sprung im Gewichtsverlauf. Mit Kinderarzt besprechen.",
        context={"z_latest": round(z1, 2), "z_prev": round(z2, 2), "delta": round(delta, 2)},
    )


# --- Registry -----------------------------------------------------------------

@dataclass
class WarningRule:
    code: str
    label: str
    description: str
    default_severity: str
    check: Callable[[Session, Child, datetime], WarningItem | None]


ALL_RULES: list[WarningRule] = [
    WarningRule(
        code="weight_loss_10",
        label="Gewichtsverlust >10 %",
        description="Warnt, wenn das Gewicht in den ersten 14 Tagen mehr als 10 % unter das Geburtsgewicht fällt.",
        default_severity="critical",
        check=check_weight_loss,
    ),
    WarningRule(
        code="fever",
        label="Fieber",
        description="Warnt bei Temperatur über altersabhängiger Schwelle (<6 Mt: 38 °C · >6 Mt: 38.5 °C).",
        default_severity="critical",
        check=check_fever,
    ),
    WarningRule(
        code="low_pees",
        label="Zu wenig Pipi",
        description="Ab Tag 5 sind mind. 6 Pipi/Tag erwartet. Prüft abends (ab 18 Uhr).",
        default_severity="warn",
        check=check_low_pees,
    ),
    WarningRule(
        code="no_feed_4h",
        label="Keine Mahlzeit seit >4h",
        description="Warnt tagsüber (7–22 Uhr), wenn über 4 Stunden nichts getrunken wurde.",
        default_severity="warn",
        check=check_no_feed,
    ),
    WarningRule(
        code="percentile_jump",
        label="Perzentilen-Sprung Gewicht",
        description="Warnt, wenn zwischen zwei Gewichtsmessungen der Z-Score um mehr als 2 springt.",
        default_severity="warn",
        check=check_percentile_jump,
    ),
]

RULES_BY_CODE: dict[str, WarningRule] = {r.code: r for r in ALL_RULES}


# --- Config helpers -----------------------------------------------------------

def get_rule_config(session: Session, code: str) -> WarningRuleConfig:
    cfg = session.get(WarningRuleConfig, code)
    if cfg is None:
        cfg = WarningRuleConfig(code=code, enabled=True, push_enabled=True)
        session.add(cfg)
        session.flush()
    return cfg


def all_rule_configs(session: Session) -> dict[str, WarningRuleConfig]:
    return {r.code: get_rule_config(session, r.code) for r in ALL_RULES}


def set_rule_enabled(session: Session, code: str, enabled: bool) -> None:
    cfg = get_rule_config(session, code)
    cfg.enabled = enabled
    session.add(cfg)
    session.commit()


def set_rule_push_enabled(session: Session, code: str, push_enabled: bool) -> None:
    cfg = get_rule_config(session, code)
    cfg.push_enabled = push_enabled
    session.add(cfg)
    session.commit()


def is_enabled(session: Session, code: str) -> bool:
    return get_rule_config(session, code).enabled


def is_push_enabled(session: Session, code: str) -> bool:
    return get_rule_config(session, code).push_enabled


# --- Runner -------------------------------------------------------------------

def run_all(session: Session, child: Child, now: datetime | None = None) -> list[WarningItem]:
    """Führt alle *aktivierten* Regeln aus."""
    now = now or datetime.now(TZ)
    results: list[WarningItem] = []
    for rule in ALL_RULES:
        if not is_enabled(session, rule.code):
            continue
        try:
            w = rule.check(session, child, now)
            if w:
                results.append(w)
        except Exception:
            continue
    return results
