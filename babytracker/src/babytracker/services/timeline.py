"""Aggregiert alle Events aus Feeding/Diaper/Sleep/Vital/Health/Med/MotherLog/Note
in einen chronologischen Zeitstrahl. Für die Tagesverlauf-Seite.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.models import (
    Child,
    Diaper,
    Feeding,
    HealthEvent,
    Measurement,
    Medication,
    MotherLog,
    Note,
    SleepSession,
    Vital,
)
from babytracker.services.daily import as_aware

TZ = ZoneInfo(settings.timezone)


@dataclass
class TimelineEvent:
    when: datetime
    category: str
    icon: str
    title: str
    detail: str = ""
    extra_class: str = ""  # optional CSS-Klasse (z.B. für kritisch)
    edit_url: str = ""  # relativer Pfad für Edit-Link


def _feed_line(f: Feeding) -> TimelineEvent:
    if f.kind == "breast":
        total = (f.duration_left_min or 0) + (f.duration_right_min or 0)
        parts = []
        if f.duration_left_min:
            parts.append(f"L {f.duration_left_min} min")
        if f.duration_right_min:
            parts.append(f"R {f.duration_right_min} min")
        detail = f"{total} Min · " + " · ".join(parts) if parts else f"{total} Min"
    else:
        offered = f.bottle_offered_ml or 0
        taken = f.bottle_taken_ml or 0
        detail = f"{taken}/{offered} ml"
        if f.bottle_type:
            detail += f" · {f.bottle_type}"
    if f.spit_up:
        detail += " · 🤢 gespuckt"
    if f.notes:
        detail += f" · {f.notes}"
    return TimelineEvent(
        when=as_aware(f.started_at),
        category="feed",
        icon="🤱" if f.kind == "breast" else "🍼",
        title=("Stillen" if f.kind == "breast" else "Flasche"),
        detail=detail,
        edit_url=f"/feed/{f.id}/edit",
    )


def _diaper_line(d: Diaper) -> TimelineEvent:
    amount_de = {"light": "wenig", "normal": "normal", "heavy": "viel"}
    parts = []
    if d.pee:
        s = "Pipi"
        if d.pee_amount:
            s += f" ({amount_de.get(d.pee_amount, d.pee_amount)})"
        parts.append(s)
    if d.stool:
        s = "Stuhl"
        if d.stool_amount:
            s += f" ({amount_de.get(d.stool_amount, d.stool_amount)})"
        if d.stool_color:
            s += f" · {d.stool_color}"
        parts.append(s)
    detail = " + ".join(parts)
    if d.stool_consistency:
        detail += f" · {d.stool_consistency}"
    if d.notes:
        detail += f" · {d.notes}"
    icon = "💩" if d.stool else "💧"
    return TimelineEvent(
        when=as_aware(d.changed_at),
        category="diaper",
        icon=icon,
        title="Windel",
        detail=detail,
        edit_url=f"/diaper/{d.id}/edit",
    )


def _sleep_line(s: SleepSession) -> list[TimelineEvent]:
    edit = f"/sleep/{s.id}/edit"
    events = [
        TimelineEvent(
            when=as_aware(s.started_at),
            category="sleep",
            icon="😴",
            title="Eingeschlafen",
            detail=("📍 " + s.location) if s.location else "",
            edit_url=edit,
        )
    ]
    if s.ended_at:
        dur = int((as_aware(s.ended_at) - as_aware(s.started_at)).total_seconds() / 60)
        events.append(
            TimelineEvent(
                when=as_aware(s.ended_at),
                category="sleep",
                icon="⏰",
                title="Aufgewacht",
                detail=f"{dur} Min geschlafen" + ((" · " + s.notes) if s.notes else ""),
                edit_url=edit,
            )
        )
    return events


def _vital_line(v: Vital) -> TimelineEvent:
    if v.kind == "temp_body":
        return TimelineEvent(
            when=as_aware(v.measured_at),
            category="health",
            icon="🌡️",
            title="Temperatur",
            detail=f"{v.value:.1f} °C",
            extra_class=("text-rose-600 font-semibold" if v.value >= 38.0 else ""),
            edit_url=f"/health/temp/{v.id}/edit",
        )
    return TimelineEvent(
        when=as_aware(v.measured_at),
        category="vital",
        icon="📈",
        title=v.kind,
        detail=f"{v.value}",
    )


def _health_line(e: HealthEvent) -> TimelineEvent:
    labels = {
        "jaundice": ("🟡", "Ikterus"),
        "umbilical": ("🩹", "Nabel"),
        "skin": ("🧴", "Haut"),
        "crying": ("😭", "Schreiphase"),
    }
    icon, title = labels.get(e.category, ("❓", e.category))
    parts = []
    if e.score is not None:
        parts.append(f"Stufe {e.score}")
    if e.status:
        parts.append(e.status)
    if e.notes:
        parts.append(e.notes)
    return TimelineEvent(
        when=as_aware(e.recorded_at),
        category="health",
        icon=icon,
        title=title,
        detail=" · ".join(parts) if parts else "",
        edit_url=f"/health/event/{e.id}/edit",
    )


def _med_line(m: Medication) -> TimelineEvent:
    detail = f"{m.dose_value} {m.dose_unit} · {m.route}"
    if m.notes:
        detail += f" · {m.notes}"
    return TimelineEvent(
        when=as_aware(m.given_at),
        category="med",
        icon="💊",
        title=m.med_name,
        detail=detail,
        edit_url=f"/meds/{m.id}/edit",
    )


def _mother_line(m: MotherLog) -> TimelineEvent:
    category_labels = {
        "clexane": ("💉", "Clexane"),
        "thrombosis_check": ("🦵", "Thrombose-Check"),
        "wound": ("🩹", "Wunde"),
        "bp": ("❤️", "Blutdruck"),
        "pulse": ("💓", "Puls"),
        "epds": ("📋", "EPDS"),
        "mood": ("😊", "Stimmung"),
        "lochia": ("🩸", "Wochenfluss"),
    }
    mood_emojis = {1: "😢", 2: "😔", 3: "😐", 4: "🙂", 5: "😄"}
    mood_labels = {1: "Sehr schlecht", 2: "Schlecht", 3: "Neutral", 4: "Gut", 5: "Sehr gut"}
    icon, title = category_labels.get(m.category, ("🤱", m.category))
    parts = []
    if m.category == "mood" and m.value_num is not None:
        val = int(m.value_num)
        icon = mood_emojis.get(val, icon)
        parts.append(mood_labels.get(val, str(val)))
    elif m.value_num is not None:
        parts.append(f"{m.value_num}")
    if m.value_text:
        parts.append(m.value_text)
    if m.notes:
        parts.append(m.notes)
    edit = f"/mother/{m.category}/{m.id}/edit" if m.category in (
        "clexane", "thrombosis_check", "wound", "bp", "lochia"
    ) else ""
    return TimelineEvent(
        when=as_aware(m.logged_at),
        category="mother",
        icon=icon,
        title=f"Mama · {title}",
        detail=" · ".join(parts) if parts else "",
        edit_url=edit,
    )


def _note_line(n: Note) -> TimelineEvent:
    return TimelineEvent(
        when=as_aware(n.logged_at),
        category="note",
        icon="📝",
        title="Notiz",
        detail=n.body,
        edit_url=f"/notes/{n.id}/edit",
    )


def _measurement_line(m: Measurement) -> TimelineEvent:
    icons = {"weight": "⚖️", "length": "📏", "head": "🧢"}
    labels = {"weight": "Gewicht", "length": "Länge", "head": "Kopfumfang"}
    if m.kind == "weight":
        detail = f"{m.value:.0f} g"
    else:
        detail = f"{m.value:.1f} cm"
    if m.source and m.source != "home":
        detail += f" · {m.source}"
    return TimelineEvent(
        when=as_aware(m.measured_at),
        category="growth",
        icon=icons.get(m.kind, "📊"),
        title=labels.get(m.kind, m.kind),
        detail=detail,
        edit_url=f"/growth/{m.id}/edit",
    )


def events_for_range(
    session: Session,
    child: Child,
    start_utc: datetime,
    end_utc: datetime,
) -> list[TimelineEvent]:
    """Alle Events zwischen start und end (exclusive), chronologisch absteigend."""
    out: list[TimelineEvent] = []

    for f in session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .where(Feeding.started_at >= start_utc, Feeding.started_at < end_utc)
    ).all():
        out.append(_feed_line(f))

    for d in session.exec(
        select(Diaper)
        .where(Diaper.child_id == child.id)
        .where(Diaper.changed_at >= start_utc, Diaper.changed_at < end_utc)
    ).all():
        out.append(_diaper_line(d))

    for s in session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child.id)
        .where(SleepSession.started_at >= start_utc, SleepSession.started_at < end_utc)
    ).all():
        out.extend(_sleep_line(s))

    for v in session.exec(
        select(Vital)
        .where(Vital.child_id == child.id, Vital.source == "manual")
        .where(Vital.measured_at >= start_utc, Vital.measured_at < end_utc)
    ).all():
        out.append(_vital_line(v))

    for e in session.exec(
        select(HealthEvent)
        .where(HealthEvent.child_id == child.id)
        .where(HealthEvent.recorded_at >= start_utc, HealthEvent.recorded_at < end_utc)
    ).all():
        out.append(_health_line(e))

    for m in session.exec(
        select(Medication)
        .where(Medication.child_id == child.id)
        .where(Medication.given_at >= start_utc, Medication.given_at < end_utc)
    ).all():
        out.append(_med_line(m))

    for ml in session.exec(
        select(MotherLog)
        .where(MotherLog.logged_at >= start_utc, MotherLog.logged_at < end_utc)
    ).all():
        out.append(_mother_line(ml))

    for n in session.exec(
        select(Note)
        .where(Note.logged_at >= start_utc, Note.logged_at < end_utc)
    ).all():
        out.append(_note_line(n))

    for m in session.exec(
        select(Measurement)
        .where(Measurement.child_id == child.id)
        .where(Measurement.measured_at >= start_utc, Measurement.measured_at < end_utc)
    ).all():
        out.append(_measurement_line(m))

    out.sort(key=lambda e: e.when, reverse=True)
    return out


def group_by_day(events: list[TimelineEvent]) -> list[tuple[str, list[TimelineEvent]]]:
    """Gruppiert Events nach Tag (lokaler Zeit). Returns (day-label, events)."""
    groups: dict[str, list[TimelineEvent]] = {}
    for e in events:
        key = e.when.astimezone(TZ).strftime("%Y-%m-%d")
        groups.setdefault(key, []).append(e)
    return sorted(groups.items(), key=lambda kv: kv[0], reverse=True)


def day_range_utc(day_iso: str) -> tuple[datetime, datetime]:
    d = datetime.strptime(day_iso, "%Y-%m-%d").date()
    start = datetime.combine(d, time.min, tzinfo=TZ)
    return start, start + timedelta(days=1)


def week_range_utc(today: datetime, days: int = 7) -> tuple[datetime, datetime]:
    end = datetime.combine(today.date(), time.min, tzinfo=TZ) + timedelta(days=1)
    start = end - timedelta(days=days)
    return start, end
