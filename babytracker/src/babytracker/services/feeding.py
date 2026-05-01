"""Mahlzeiten-Logik: Combo-Gruppierung (Stillen + Schoppen <20 Min danach = 1
Mahlzeit), Hebammen-Faustregel für Tages-Trinkbedarf, Schnitt der letzten 5 Tage.

Stillen-Volumen wird mit ``BREAST_ML_PER_MIN`` (1.5 ml/min) geschätzt.
Tages-Trinkbedarf = max(birth_weight_g, max(weight_measurements)) / 6 in ml.
Bei 4'200 g → 700 ml/Tag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.models import Child, Feeding, Measurement
from babytracker.services.daily import as_aware

TZ = ZoneInfo(settings.timezone)

#: Faustregel Hebamme: 1.5 ml geschätzte Trinkmenge pro Stillminute.
BREAST_ML_PER_MIN: float = 1.5

#: Combo-Fenster: Schoppen innerhalb dieser Zeit nach Stillende zählt zur
#: gleichen Mahlzeit – kein Stilldauer-Penalty fürs Intervall.
COMBO_WINDOW_MIN: int = 20

#: Tagesbedarf wird über den Schnitt der letzten N Tage / Mahlzeiten geteilt.
AVG_WINDOW_DAYS: int = 5


@dataclass
class Meal:
    """Eine logische Mahlzeit. Kann eine reine Stillsitzung, eine reine
    Flaschenmahlzeit oder eine Combo (Stillen + Schoppen <20 Min danach) sein.
    """

    start_at: datetime
    end_at: datetime
    breast_min: int = 0
    bottle_ml: int = 0
    has_breast: bool = False
    has_bottle: bool = False

    @property
    def is_combo(self) -> bool:
        return self.has_breast and self.has_bottle

    @property
    def estimated_ml(self) -> int:
        """Geschätzte Gesamttrinkmenge: Schoppen (gemessen) + Stillen × 1.5 ml/min."""
        return int(round(self.bottle_ml + self.breast_min * BREAST_ML_PER_MIN))


def _feed_end(f: Feeding) -> datetime:
    """Endzeit einer Feeding-Zeile. Stillen: ``ended_at`` (in routes/feed.py
    auf ``started_at + total_min`` gesetzt). Flasche: ``ended_at`` ist None,
    Approximation = ``started_at`` (ein Schoppen dauert nur ~10 Min).
    """
    end = as_aware(f.ended_at) if f.ended_at else None
    return end or as_aware(f.started_at)


def _breast_total_min(f: Feeding) -> int:
    return (f.duration_left_min or 0) + (f.duration_right_min or 0)


def group_into_meals(
    feedings: list[Feeding],
    combo_window_min: int = COMBO_WINDOW_MIN,
) -> list[Meal]:
    """Gruppiert chronologisch sortierte Feeding-Einträge in logische Mahlzeiten.

    Combo-Regel (nur Stillen → Schoppen, asymmetrisch): Ein Schoppen wird zur
    laufenden Mahlzeit gezählt, wenn (a) die laufende Mahlzeit Stillen enthält
    und (b) der Schoppen innerhalb ``combo_window_min`` Minuten nach dem Ende
    der laufenden Mahlzeit beginnt. In allen anderen Fällen (Stillen→Stillen,
    Schoppen→Stillen, Schoppen→Schoppen) wird eine neue Mahlzeit eröffnet.

    Begründung: Hebammen-Faustregel betrachtet "Stillen + Schoppen als
    Auffüllung" als eine Mahlzeit. Zwei Stillen-Sitzungen kurz hintereinander
    gelten dagegen als zwei Mahlzeiten – konsistent mit der Roh-Anzeige im
    Verlauf-Filter.
    """
    sorted_feeds = sorted(feedings, key=lambda f: as_aware(f.started_at))
    meals: list[Meal] = []
    current: Meal | None = None
    window = timedelta(minutes=combo_window_min)

    for f in sorted_feeds:
        f_start = as_aware(f.started_at)
        f_end = _feed_end(f)

        is_followup_bottle = (
            current is not None
            and f.kind == "bottle"
            and current.has_breast
            and f_start - current.end_at <= window
        )

        if is_followup_bottle:
            target = current
        else:
            target = Meal(start_at=f_start, end_at=f_end)
            meals.append(target)
            current = target

        if f_end > target.end_at:
            target.end_at = f_end

        if f.kind == "breast":
            target.has_breast = True
            target.breast_min += _breast_total_min(f)
        elif f.kind == "bottle":
            target.has_bottle = True
            target.bottle_ml += f.bottle_taken_ml or 0

    return meals


def last_meal(session: Session, child: Child) -> Meal | None:
    """Letzte Mahlzeit (Combo-Gruppierung berücksichtigt). Schaut auf die
    letzten 24 h zurück – das genügt für das Mahlzeit-Intervall.
    """
    cutoff = datetime.now(TZ) - timedelta(hours=24)
    feedings = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .where(Feeding.started_at >= cutoff)
        .order_by(Feeding.started_at.asc())
    ).all()
    if not feedings:
        latest = session.exec(
            select(Feeding)
            .where(Feeding.child_id == child.id)
            .order_by(Feeding.started_at.desc())
        ).first()
        if not latest:
            return None
        feedings = [latest]

    meals = group_into_meals(feedings)
    return meals[-1] if meals else None


def reference_weight_g(session: Session, child: Child) -> int | None:
    """Referenzgewicht für Trinkbedarfs-Berechnung: das höchste je gemessene
    Gewicht (inkl. Geburtsgewicht). Verhindert, dass ein temporärer Verlust
    den empfohlenen Tagesbedarf nach unten zieht.
    """
    max_meas = session.exec(
        select(Measurement.value)
        .where(Measurement.child_id == child.id, Measurement.kind == "weight")
        .order_by(Measurement.value.desc())
    ).first()
    candidates: list[float] = []
    if child.birth_weight_g:
        candidates.append(float(child.birth_weight_g))
    if max_meas is not None:
        candidates.append(float(max_meas))
    if not candidates:
        return None
    return int(round(max(candidates)))


@dataclass
class DailyRecommendation:
    """Tagesbedarfs-Berechnung nach Hebammen-Faustregel."""

    daily_ml: int
    """Tagesbedarf in ml = Referenzgewicht / 6 (mL)."""

    reference_weight_g: int
    """Höchstes je erfasstes Gewicht (inkl. Geburtsgewicht) in g."""

    avg_meals_per_day: float
    """Schnitt Mahlzeiten/Tag der letzten ``AVG_WINDOW_DAYS`` Tage. Combos = 1."""

    avg_window_days: int
    """Anzahl tatsächlich ausgewerteter Tage (≤ AVG_WINDOW_DAYS)."""

    ml_per_meal: int
    """daily_ml / avg_meals_per_day, gerundet."""

    today_ml: int
    """Bisher heute getrunken (Schoppen + Stillen × 1.5 ml/min)."""

    today_meals: int
    """Mahlzeiten heute (Combos = 1)."""


def daily_recommendation(
    session: Session,
    child: Child,
    now: datetime | None = None,
) -> DailyRecommendation | None:
    """Berechnet Tagesbedarf, Schnitt Mahlzeiten/Tag und ml/Mahlzeit.

    Returns ``None``, wenn weder Geburts- noch gemessenes Gewicht vorliegt.
    """
    now = now or datetime.now(TZ)
    ref_g = reference_weight_g(session, child)
    if ref_g is None:
        return None

    daily_ml = int(round(ref_g / 6))

    today = now.date()
    window_start_date = today - timedelta(days=AVG_WINDOW_DAYS)
    window_start_utc = datetime.combine(window_start_date, time.min, tzinfo=TZ)
    today_start_utc = datetime.combine(today, time.min, tzinfo=TZ)
    today_end_utc = today_start_utc + timedelta(days=1)

    history = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .where(Feeding.started_at >= window_start_utc, Feeding.started_at < today_start_utc)
        .order_by(Feeding.started_at.asc())
    ).all()
    history_meals = group_into_meals(history)

    days_with_data: set[str] = set()
    for m in history_meals:
        days_with_data.add(m.start_at.astimezone(TZ).strftime("%Y-%m-%d"))
    avg_window = max(1, len(days_with_data))
    avg_meals = len(history_meals) / avg_window if avg_window else 0.0

    today_feeds = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .where(Feeding.started_at >= today_start_utc, Feeding.started_at < today_end_utc)
        .order_by(Feeding.started_at.asc())
    ).all()
    today_meal_list = group_into_meals(today_feeds)
    today_ml = sum(m.estimated_ml for m in today_meal_list)
    today_meals = len(today_meal_list)

    if avg_meals > 0:
        ml_per_meal = int(round(daily_ml / avg_meals))
    elif today_meals > 0:
        ml_per_meal = int(round(daily_ml / today_meals))
    else:
        ml_per_meal = int(round(daily_ml / 8))

    return DailyRecommendation(
        daily_ml=daily_ml,
        reference_weight_g=ref_g,
        avg_meals_per_day=round(avg_meals, 1),
        avg_window_days=avg_window,
        ml_per_meal=ml_per_meal,
        today_ml=today_ml,
        today_meals=today_meals,
    )


@dataclass
class DayBreakdown:
    """Tagesbilanz für die 30-Tage-Übersicht auf der Ernährungs-Seite."""

    date_iso: str           # "2026-05-01"
    weekday: str            # "Do"
    day_of_life: int        # Lebenstag (Tag 1 = Geburtstag)
    meals: int              # Anzahl Mahlzeiten (Combo-aware)
    breast_min: int
    bottle_ml: int
    estimated_ml: int       # Schoppen + Stillen × 1.5 ml/min
    daily_target_ml: int
    pct: int                # estimated_ml / daily_target_ml × 100, gecappt 100


_WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def daily_breakdown(
    session: Session,
    child: Child,
    days: int = 30,
    now: datetime | None = None,
) -> list[DayBreakdown]:
    """Liefert pro Tag der letzten ``days`` Tage eine Bilanz, neueste zuerst.

    Mahlzeiten sind Combo-aware (Stillen + Schoppen <20 Min = 1). Tagesbedarf
    ist konstant über alle Tage = aktuelles Referenzgewicht / 6 (vereinfacht;
    historische Gewichts-Veränderung wird nicht rückwirkend angewendet).
    """
    now = now or datetime.now(TZ)
    today = now.date()
    end_date = today
    start_date = today - timedelta(days=days - 1)

    start_utc = datetime.combine(start_date, time.min, tzinfo=TZ)
    end_utc = datetime.combine(end_date, time.min, tzinfo=TZ) + timedelta(days=1)

    feeds = session.exec(
        select(Feeding)
        .where(Feeding.child_id == child.id)
        .where(Feeding.started_at >= start_utc, Feeding.started_at < end_utc)
        .order_by(Feeding.started_at.asc())
    ).all()

    by_day: dict[str, list[Feeding]] = {}
    for f in feeds:
        key = as_aware(f.started_at).astimezone(TZ).strftime("%Y-%m-%d")
        by_day.setdefault(key, []).append(f)

    ref_g = reference_weight_g(session, child)
    daily_target = int(round(ref_g / 6)) if ref_g else 0
    birth_local = as_aware(child.birth_at).astimezone(TZ).date() if child.birth_at else None

    out: list[DayBreakdown] = []
    cursor = end_date
    while cursor >= start_date:
        key = cursor.strftime("%Y-%m-%d")
        day_feeds = by_day.get(key, [])
        meals = group_into_meals(day_feeds)
        breast_min = sum(_breast_total_min(f) for f in day_feeds)
        bottle_ml = sum((f.bottle_taken_ml or 0) for f in day_feeds)
        est_ml = sum(m.estimated_ml for m in meals)
        pct = 0
        if daily_target > 0:
            pct = min(100, int(round(est_ml / daily_target * 100)))
        day_of_life = (cursor - birth_local).days + 1 if birth_local else 0
        out.append(DayBreakdown(
            date_iso=key,
            weekday=_WEEKDAYS_DE[cursor.weekday()],
            day_of_life=day_of_life,
            meals=len(meals),
            breast_min=breast_min,
            bottle_ml=bottle_ml,
            estimated_ml=est_ml,
            daily_target_ml=daily_target,
            pct=pct,
        ))
        cursor -= timedelta(days=1)

    return out
