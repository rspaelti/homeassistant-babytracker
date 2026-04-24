"""Owlet Dream Sock → HA-REST-API → vitals-Tabelle.

Holt alle 10 Min. die aktuellen States der Owlet-Entitäten, aggregiert sie
als Min/Max/Avg-Bucket und speichert in der `vitals`-Tabelle.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.db import engine
from babytracker.models import Child, SleepSession, Vital
from babytracker.services.ha_client import get_state

log = logging.getLogger(__name__)
TZ = ZoneInfo(settings.timezone)

# (HA-Suffix nach Prefix, interne Bezeichnung in vitals.kind, Einheit)
SENSOR_MAP = [
    ("heart_rate", "heart_rate", "bpm"),
    ("o2_saturation", "spo2", "%"),
    ("o2_saturation_10_minute_average", "spo2_avg10", "%"),
    ("skin_temperature", "temp_skin", "°C"),
    ("movement", "movement", ""),
    ("battery_percentage", "battery_pct", "%"),
]

SLEEP_STATE_ENTITY_SUFFIX = "sleep_state"
SOCK_OFF_ENTITY_SUFFIX = "sock_off"  # binary_sensor


def _sensor_entity(suffix: str) -> str:
    return f"sensor.{settings.owlet_prefix}{suffix}"


def _binary_entity(suffix: str) -> str:
    return f"binary_sensor.{settings.owlet_prefix}{suffix}"


async def sample_once() -> dict[str, float | str | None]:
    """Holt einen einzelnen Snapshot aller Sensorwerte. Null bei Fehler."""
    out: dict[str, float | str | None] = {}
    for suffix, kind, _unit in SENSOR_MAP:
        st = await get_state(_sensor_entity(suffix))
        if not st or st.get("state") in (None, "unknown", "unavailable"):
            out[kind] = None
            continue
        try:
            out[kind] = float(st["state"])
        except (ValueError, TypeError):
            out[kind] = None
    # Sleep-State ist kein Zahlenwert
    st = await get_state(_sensor_entity(SLEEP_STATE_ENTITY_SUFFIX))
    out["sleep_state"] = st.get("state") if st else None
    # Sock angelegt? binary_sensor.…sock_off: "off" = Sock AN
    # Falls Entity fehlt oder unavailable → aus Sensordaten ableiten
    st = await get_state(_binary_entity(SOCK_OFF_ENTITY_SUFFIX))
    if st and st.get("state") not in (None, "unknown", "unavailable"):
        out["sock_worn"] = (st.get("state") == "off")
    else:
        # Fallback: Sock gilt als getragen wenn Puls oder SpO2 lesbar
        out["sock_worn"] = isinstance(out.get("heart_rate"), (int, float)) or isinstance(out.get("spo2"), (int, float))
    return out


async def sock_currently_worn() -> bool:
    """True wenn Sock aktuell getragen (sock_off = off heisst Sock ist AN)."""
    st = await get_state(_binary_entity(SOCK_OFF_ENTITY_SUFFIX))
    return bool(st and st.get("state") == "off")


@dataclass
class _Buffer:
    values: dict[str, list[float]]


_buffer = _Buffer(values=defaultdict(list))


async def collect_snapshot() -> None:
    """Läuft z.B. alle 30 Sek. — sammelt Werte im In-Memory-Buffer."""
    if not settings.ha_url or not settings.ha_token:
        log.warning("Owlet collect: ha_url/ha_token not set – skipping")
        return
    sample = await sample_once()
    if not sample.get("sock_worn"):
        log.debug(
            "Owlet collect: sock not worn (hr=%s spo2=%s)",
            sample.get("heart_rate"), sample.get("spo2"),
        )
        return
    added = 0
    for kind in ("heart_rate", "spo2", "spo2_avg10", "temp_skin"):
        v = sample.get(kind)
        if isinstance(v, (int, float)):
            _buffer.values[kind].append(float(v))
            added += 1
    log.info("Owlet collect: %d values buffered (hr=%s spo2=%s)", added, sample.get("heart_rate"), sample.get("spo2"))


async def flush_aggregates() -> None:
    """Läuft alle 10 Min. — schreibt Min/Max/Avg pro Messgrösse in vitals."""
    if not _buffer.values:
        return
    now = datetime.now(TZ)
    bucket_min = 10

    with Session(engine) as session:
        child = session.exec(
            select(Child).where(Child.active == True).order_by(Child.id)  # noqa: E712
        ).first()
        if not child:
            _buffer.values.clear()
            return

        for kind, vals in _buffer.values.items():
            if not vals:
                continue
            session.add(Vital(
                child_id=child.id, measured_at=now, kind=kind,
                value=min(vals), agg="min", bucket_min=bucket_min, source="owlet",
            ))
            session.add(Vital(
                child_id=child.id, measured_at=now, kind=kind,
                value=max(vals), agg="max", bucket_min=bucket_min, source="owlet",
            ))
            session.add(Vital(
                child_id=child.id, measured_at=now, kind=kind,
                value=round(statistics.mean(vals), 2), agg="avg",
                bucket_min=bucket_min, source="owlet",
            ))
        session.commit()

    n_kinds = sum(1 for v in _buffer.values.values() if v)
    log.info("Owlet flush: %d kinds aggregated (bucket=%dmin)", n_kinds, bucket_min)
    _buffer.values.clear()


# --- Live-Status für Home-Dashboard ------------------------------------------

@dataclass
class OwletLive:
    available: bool
    sock_worn: bool
    heart_rate: float | None
    spo2: float | None
    spo2_avg10: float | None
    temp_skin: float | None
    battery_pct: float | None
    sleep_state: str | None


async def fetch_live() -> OwletLive:
    if not settings.ha_url or not settings.ha_token:
        log.warning("fetch_live: ha_url/ha_token not set")
        return OwletLive(False, False, None, None, None, None, None, None)
    s = await sample_once()
    log.info(
        "fetch_live: sock_worn=%s hr=%s spo2=%s prefix=%s",
        s.get("sock_worn"), s.get("heart_rate"), s.get("spo2"), settings.owlet_prefix,
    )
    return OwletLive(
        available=True,
        sock_worn=bool(s.get("sock_worn")),
        heart_rate=s.get("heart_rate") if isinstance(s.get("heart_rate"), (int, float)) else None,
        spo2=s.get("spo2") if isinstance(s.get("spo2"), (int, float)) else None,
        spo2_avg10=s.get("spo2_avg10") if isinstance(s.get("spo2_avg10"), (int, float)) else None,
        temp_skin=s.get("temp_skin") if isinstance(s.get("temp_skin"), (int, float)) else None,
        battery_pct=s.get("battery_pct") if isinstance(s.get("battery_pct"), (int, float)) else None,
        sleep_state=s.get("sleep_state") if isinstance(s.get("sleep_state"), str) else None,
    )


# --- Auto-Schlaferfassung via sleep_state ------------------------------------

# Owlet liefert typischerweise: awake / light_sleep / deep_sleep / out_of_range / sleep_disturbance
_SLEEP_STATES = {"light_sleep", "deep_sleep", "sleep_disturbance"}
_AWAKE_STATES = {"awake"}


async def auto_sleep_from_owlet() -> None:
    """Öffnet/schliesst automatisch SleepSessions anhand des Owlet sleep_state.

    Regeln:
    - sleep_state ∈ {light_sleep, deep_sleep, sleep_disturbance} und keine offene Session
      → neue SleepSession mit owlet_worn=True eröffnen.
    - sleep_state == 'awake' und eine offene SleepSession mit owlet_worn=True existiert
      → diese schliessen.
    - Manuelle Sessions (owlet_worn=False) bleiben unangetastet.
    - Bei unknown/unavailable/out_of_range: nichts tun (Socke eventuell am Laden).
    """
    if not settings.ha_url or not settings.ha_token:
        return
    st = await get_state(_sensor_entity(SLEEP_STATE_ENTITY_SUFFIX))
    if not st:
        return
    state = st.get("state")
    if state in (None, "unknown", "unavailable", "out_of_range"):
        return

    now = datetime.now(TZ)
    with Session(engine) as session:
        child = session.exec(
            select(Child).where(Child.active == True).order_by(Child.id)  # noqa: E712
        ).first()
        if not child:
            return

        open_session = session.exec(
            select(SleepSession)
            .where(SleepSession.child_id == child.id)
            .where(SleepSession.ended_at.is_(None))
            .order_by(SleepSession.started_at.desc())
        ).first()

        if state in _SLEEP_STATES:
            if open_session is None:
                session.add(SleepSession(
                    child_id=child.id,
                    started_at=now,
                    owlet_worn=True,
                    notes="Automatisch via Owlet",
                ))
                session.commit()
                log.info("Auto-sleep: opened session (state=%s)", state)
        elif state in _AWAKE_STATES:
            if open_session is not None and open_session.owlet_worn:
                open_session.ended_at = now
                session.add(open_session)
                session.commit()
                log.info("Auto-sleep: closed session (state=%s)", state)


# --- Alert-Check für WarningRules --------------------------------------------

# Liste (suffix, label_de, severity)
OWLET_ALERTS = [
    ("low_oxygen_alert", "Owlet: Niedrige Sauerstoffsättigung", "critical"),
    ("low_heart_rate_alert", "Owlet: Niedriger Puls", "critical"),
    ("high_heart_rate_alert", "Owlet: Hoher Puls", "warn"),
    ("high_oxygen_alert", "Owlet: Hohe Sauerstoffsättigung", "warn"),
    ("sock_disconnected_alert", "Owlet: Sock getrennt", "warn"),
    ("lost_power_alert", "Owlet: Stromausfall", "warn"),
    ("low_battery_alert", "Owlet: Batterie niedrig", "info"),
]


async def any_active_alert() -> list[tuple[str, str, str]]:
    """Liefert Liste aktiver Alerts. Jedes: (code, title, severity)."""
    if not settings.ha_url or not settings.ha_token:
        return []
    active: list[tuple[str, str, str]] = []
    for suffix, label, severity in OWLET_ALERTS:
        st = await get_state(_binary_entity(suffix))
        if st and st.get("state") == "on":
            code = f"owlet_{suffix}"
            active.append((code, label, severity))
    return active
