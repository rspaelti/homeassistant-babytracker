"""Helper für Mama-Sektion: Clexane-Status heute, letzte Einträge etc."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.models import MotherLog
from babytracker.services.daily import as_aware, day_bounds_utc

TZ = ZoneInfo(settings.timezone)


@dataclass
class MotherOverview:
    clexane_today: MotherLog | None
    clexane_days_left: int | None  # bis Ende 6 Wochen
    thrombosis_today: MotherLog | None
    last_wound: MotherLog | None
    last_bp: MotherLog | None
    last_epds: MotherLog | None
    last_mood: MotherLog | None
    last_lochia: MotherLog | None


def _last(session: Session, category: str) -> MotherLog | None:
    return session.exec(
        select(MotherLog)
        .where(MotherLog.category == category)
        .order_by(MotherLog.logged_at.desc())
    ).first()


def _today(session: Session, category: str, today: date) -> MotherLog | None:
    start, end = day_bounds_utc(today)
    return session.exec(
        select(MotherLog)
        .where(MotherLog.category == category)
        .where(MotherLog.logged_at >= start, MotherLog.logged_at < end)
        .order_by(MotherLog.logged_at.desc())
    ).first()


def compute_clexane_end_date(birth_at: datetime | None) -> date | None:
    """6 Wochen postpartal, gemäss Standard-Therapie bei Thrombophilie."""
    if not birth_at:
        return None
    return (as_aware(birth_at) + timedelta(days=42)).date()


def overview(session: Session, birth_at: datetime | None, now: datetime | None = None) -> MotherOverview:
    now = now or datetime.now(TZ)
    today = now.date()

    clexane_end = compute_clexane_end_date(birth_at)
    days_left = (clexane_end - today).days if clexane_end else None

    return MotherOverview(
        clexane_today=_today(session, "clexane", today),
        clexane_days_left=days_left,
        thrombosis_today=_today(session, "thrombosis_check", today),
        last_wound=_last(session, "wound"),
        last_bp=_last(session, "bp"),
        last_epds=_last(session, "epds"),
        last_mood=_last(session, "mood"),
        last_lochia=_last(session, "lochia"),
    )


# EPDS: offizielle 10 Items (Edinburgh Postnatal Depression Scale)
# Jede Frage 0–3 Punkte. Summe 0–30. ≥10 = möglicherweise Depression, ≥13 = wahrscheinlich.
EPDS_QUESTIONS: list[tuple[str, list[tuple[int, str]]]] = [
    ("Ich konnte lachen und die heitere Seite der Dinge sehen …", [
        (0, "so oft wie immer"),
        (1, "nicht ganz so oft wie sonst"),
        (2, "deutlich seltener als sonst"),
        (3, "überhaupt nicht"),
    ]),
    ("Ich konnte mich so richtig auf etwas freuen …", [
        (0, "so sehr wie immer"),
        (1, "ein bisschen weniger als sonst"),
        (2, "deutlich weniger als sonst"),
        (3, "kaum"),
    ]),
    ("Ich habe mir unnötig Schuldgefühle gemacht, wenn etwas schiefging …", [
        (3, "ja, die meiste Zeit"),
        (2, "ja, manchmal"),
        (1, "nicht sehr oft"),
        (0, "nein, nie"),
    ]),
    ("Ich war ängstlich und besorgt aus nichtigem Anlass …", [
        (0, "nein, gar nicht"),
        (1, "selten"),
        (2, "ja, manchmal"),
        (3, "ja, sehr oft"),
    ]),
    ("Ich habe mich aus nichtigen Gründen ängstlich oder panisch gefühlt …", [
        (3, "ja, ziemlich oft"),
        (2, "ja, manchmal"),
        (1, "nein, nicht oft"),
        (0, "nein, überhaupt nicht"),
    ]),
    ("Viele Dinge sind mir über den Kopf gewachsen …", [
        (3, "ja, meistens"),
        (2, "ja, manchmal"),
        (1, "nein, meistens nicht"),
        (0, "nein, überhaupt nicht"),
    ]),
    ("Ich war so unglücklich, dass ich nicht schlafen konnte …", [
        (3, "ja, meistens"),
        (2, "ja, manchmal"),
        (1, "nein, nicht oft"),
        (0, "nein, überhaupt nicht"),
    ]),
    ("Ich habe mich traurig und elend gefühlt …", [
        (3, "ja, meistens"),
        (2, "ja, ziemlich oft"),
        (1, "selten"),
        (0, "nein, überhaupt nicht"),
    ]),
    ("Ich war so unglücklich, dass ich geweint habe …", [
        (3, "ja, meistens"),
        (2, "ja, ziemlich oft"),
        (1, "nur gelegentlich"),
        (0, "nein, niemals"),
    ]),
    ("Der Gedanke, mir selbst etwas anzutun, kam mir …", [
        (3, "ja, ziemlich oft"),
        (2, "manchmal"),
        (1, "kaum"),
        (0, "niemals"),
    ]),
]


def epds_interpret(score: int) -> tuple[str, str]:
    if score <= 9:
        return ("low", "Niedriges Risiko. Regelmässig wiederholen.")
    if score <= 12:
        return ("moderate", "Möglicher Hinweis auf Wochenbettdepression. Mit Hebamme / Arzt besprechen.")
    return ("high", "Wahrscheinlicher Hinweis auf Wochenbettdepression. Bitte zeitnah ärztliche Hilfe.")
