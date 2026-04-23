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


def _base_interval_hours(age_days: int) -> float:
    """Alters-abhängiges Basis-Intervall (Schweiz / WHO / Stillstiftung):
    Neugeborene 8–12 Mahlzeiten/24h → alle 2–3h, später verdünnt sich das.
    """
    if age_days < 28:
        return 2.5
    if age_days < 90:
        return 3.0
    if age_days < 180:
        return 3.5
    return 4.0


def _weight_loss_adjustment(session: Session, child: Child) -> tuple[float, str | None]:
    """Bei Gewichtsverlust häufiger stillen. Ermittelt Delta-Stunden (negativ)."""
    if not child.birth_weight_g:
        return 0.0, None
    latest = session.exec(
        select(Measurement)
        .where(Measurement.child_id == child.id, Measurement.kind == "weight")
        .order_by(Measurement.measured_at.desc())
    ).first()
    if not latest or latest.value >= child.birth_weight_g:
        return 0.0, None
    loss_pct = (child.birth_weight_g - latest.value) / child.birth_weight_g * 100
    if loss_pct > 10:
        return -1.0, f"Gewichtsverlust {loss_pct:.1f}%"
    if loss_pct > 7:
        return -0.5, f"Gewichtsverlust {loss_pct:.1f}%"
    return 0.0, None


def _breast_duration_adjustment(last: Feeding) -> tuple[float, str | None]:
    """Wenn die letzte Still-Einheit kürzer war als ideal, häufiger erinnern.

    Ideal: 15 Min pro gestillter Seite (15 bei einseitig, 30 bei beidseitig).
    Toleranz ±10 Min. Darunter: -30 Min, bei >20 Min Delta: -60 Min.
    """
    if last.kind != "breast":
        return 0.0, None
    left = last.duration_left_min or 0
    right = last.duration_right_min or 0
    actual = left + right
    if actual <= 0:
        return 0.0, None

    sides_used = (1 if left > 0 else 0) + (1 if right > 0 else 0)
    if sides_used == 0:
        return 0.0, None
    ideal = 15 * sides_used
    delta = ideal - actual
    if delta > 20:
        return -1.0, f"letzte Mahlzeit nur {actual} Min (soll ~{ideal})"
    if delta > 10:
        return -0.5, f"letzte Mahlzeit {actual} Min (soll ~{ideal})"
    return 0.0, None


@dataclass
class FeedIntervalEstimate:
    hours: float
    base_hours: float
    reasons: list[str]


def estimate_feed_interval(session: Session, child: Child, now: datetime) -> FeedIntervalEstimate:
    """Berechnet das erwartete Intervall bis zur nächsten Mahlzeit."""
    age = _age_days(child, now)
    base = _base_interval_hours(age)
    reasons: list[str] = []
    total = base

    w_adj, w_reason = _weight_loss_adjustment(session, child)
    total += w_adj
    if w_reason:
        reasons.append(f"{w_reason} {w_adj:+.1f}h")

    last_feed = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .order_by(Feeding.started_at.desc())
    ).first()
    if last_feed:
        d_adj, d_reason = _breast_duration_adjustment(last_feed)
        total += d_adj
        if d_reason:
            reasons.append(f"{d_reason} {d_adj:+.1f}h")

    total = max(1.5, total)
    return FeedIntervalEstimate(hours=total, base_hours=base, reasons=reasons)


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
    hours_since = (now - last_at).total_seconds() / 3600

    est = estimate_feed_interval(session, child, now)
    if hours_since < est.hours:
        return None

    reason_tail = ""
    if est.reasons:
        reason_tail = " · " + ", ".join(est.reasons)

    return WarningItem(
        code="no_feed_4h",
        severity="warn",
        title=f"Mahlzeit fällig – seit {hours_since:.1f}h nichts",
        message=(
            f"Empfohlenes Intervall aktuell {est.hours:.1f}h "
            f"(Basis {est.base_hours:.1f}h für Alter){reason_tail}."
        ),
        context={
            "hours_since": round(hours_since, 1),
            "expected": round(est.hours, 2),
            "base": round(est.base_hours, 2),
            "reasons": est.reasons,
            "last_at": last_at.isoformat(),
        },
    )


def check_owlet_alerts(session: Session, child: Child, now: datetime) -> WarningItem | None:
    """Synchroner Owlet-Check: liest aktuelle binary_sensor-States aus HA-State-Cache.

    Der async-fetch_live passt nicht in den sync-check Pattern. Wir lesen
    stattdessen den letzten Sync-Snapshot aus dem Buffer oder verzichten hier.
    Die echten Owlet-Alerts werden vom Scheduler-Owlet-Job direkt in WarningState geschrieben.
    """
    return None  # placeholder, Owlet-Alerts laufen über separaten Scheduler-Pfad


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


def _no_check(session: Session, child: Child, now: datetime) -> WarningItem | None:
    """Dummy-Check für zeitbasierte Reminder — werden nicht im run_all ausgelöst,
    sondern direkt via Scheduler-Cron-Jobs gepusht."""
    return None


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
        label="Mahlzeit-Intervall überschritten",
        description=(
            "Dynamisches Intervall (Basis 2.5–4h nach Alter), "
            "kürzer bei Gewichtsverlust und wenn die letzte Stillzeit unter dem Ideal war "
            "(15 Min pro gestillter Seite). Warnt tagsüber 7–22 Uhr."
        ),
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
    # --- Zeitbasierte Reminder (Cron-Jobs, kein State-Check) ---
    WarningRule(
        code="reminder_weight_morning",
        label="⏰ Gewicht-Erinnerung 09:00",
        description="Tägliche Push-Erinnerung um 09:00 Uhr zur Gewichtsmessung.",
        default_severity="info",
        check=_no_check,
    ),
    WarningRule(
        code="reminder_weight_late",
        label="⏰ Gewicht-Nachzügler 10:00",
        description="Falls bis 10:00 Uhr kein Gewicht eingetragen wurde, kommt ein zweiter Push.",
        default_severity="info",
        check=_no_check,
    ),
    WarningRule(
        code="reminder_vitd_morning",
        label="⏰ Vitamin-D-Erinnerung 09:00",
        description="Tägliche Push-Erinnerung um 09:00 Uhr zur Vitamin-D-Gabe.",
        default_severity="info",
        check=_no_check,
    ),
    WarningRule(
        code="reminder_vitd_late",
        label="⏰ Vitamin-D-Nachzügler 10:00",
        description="Falls bis 10:00 Uhr keine Vitamin-D-Gabe eingetragen wurde, kommt ein zweiter Push.",
        default_severity="info",
        check=_no_check,
    ),
    WarningRule(
        code="reminder_length_morning",
        label="⏰ Länge/Kopf Sonntag 09:00",
        description="Wöchentliche Sonntag-Erinnerung um 09:00 Uhr für Länge + Kopfumfang.",
        default_severity="info",
        check=_no_check,
    ),
    WarningRule(
        code="reminder_length_late",
        label="⏰ Länge/Kopf Sonntag 10:00 Nachzügler",
        description="Falls sonntags bis 10:00 Uhr Länge/Kopfumfang fehlen, kommt ein zweiter Push.",
        default_severity="info",
        check=_no_check,
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
