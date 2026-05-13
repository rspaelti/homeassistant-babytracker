"""Tagesstatistiken für Owlet-Vitalwerte, aufgeteilt nach Tag/Nacht und
Schlaf/Wach. Datenquelle: ``vitals``-Tabelle mit ``source='owlet'`` und
``agg='avg'`` (10-Min-Buckets aus dem owlet_flush-Scheduler).

Tag = 07:00–21:59, Nacht = 22:00–06:59 (Europe/Zurich).
Schlaf/Wach wird aus den `SleepSession`-Overlappings bestimmt: ein Vital-
Datenpunkt zählt als "Schlaf" wenn er innerhalb einer Session liegt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.models import Child, SleepSession, Vital
from babytracker.services.daily import as_aware

TZ = ZoneInfo(settings.timezone)

#: Stunde, ab der "Tag" beginnt (07:00 inklusive).
DAY_START_HOUR: int = 7
#: Stunde, ab der "Nacht" beginnt (22:00 inklusive).
NIGHT_START_HOUR: int = 22

VITAL_KINDS = ("spo2", "heart_rate", "temp_skin")


@dataclass
class VitalStats:
    """Aggregat einer Metrik in einem Bucket."""
    n: int = 0
    avg: float | None = None
    min_val: float | None = None
    max_val: float | None = None


@dataclass
class VitalBucket:
    """Ein Bucket: kombination aus Tageszeit (day/night) und Zustand (sleep/awake)."""
    period: str  # "day" oder "night"
    state: str   # "sleep" oder "awake"
    duration_min: int = 0  # Wie lange in diesem Zustand
    stats: dict[str, VitalStats] = field(default_factory=dict)


@dataclass
class VitalDay:
    """Tagesstatistik mit 4 Buckets."""
    date_iso: str
    weekday: str
    day_of_life: int
    buckets: list[VitalBucket]

    def get(self, period: str, state: str) -> VitalBucket | None:
        for b in self.buckets:
            if b.period == period and b.state == state:
                return b
        return None


_WEEKDAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _classify_period(dt: datetime) -> str:
    """Tag oder Nacht anhand der lokalen Stunde."""
    h = dt.astimezone(TZ).hour
    return "day" if DAY_START_HOUR <= h < NIGHT_START_HOUR else "night"


def _build_sleep_intervals(
    sessions: list[SleepSession],
) -> list[tuple[datetime, datetime]]:
    """Wandelt SleepSession-Rows in [(start, end), ...] mit tz-aware datetimes.
    Offene Sessions (ended_at=None) werden bis 'now' gezogen.
    """
    now = datetime.now(TZ)
    intervals: list[tuple[datetime, datetime]] = []
    for s in sessions:
        start = as_aware(s.started_at)
        end = as_aware(s.ended_at) if s.ended_at else now
        if start and end and end > start:
            intervals.append((start, end))
    intervals.sort(key=lambda x: x[0])
    return intervals


def _is_sleeping(dt: datetime, intervals: list[tuple[datetime, datetime]]) -> bool:
    """Prüft ob dt in einer der Schlaf-Intervalle liegt. O(n) – akzeptabel für
    typische Tagesmengen (≤ ~50 Sessions × 7 Tage)."""
    for s, e in intervals:
        if s <= dt < e:
            return True
    return False


def _overlap_minutes(
    interval: tuple[datetime, datetime],
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Überlappung zweier Zeitintervalle in Minuten (>=0)."""
    s = max(interval[0], window_start)
    e = min(interval[1], window_end)
    if e <= s:
        return 0
    return int((e - s).total_seconds() / 60)


def _day_windows(d: date) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    """Liefert die Tag- und Nachtfenster eines lokalen Datums.

    Tag = 07:00–22:00 desselben Tages.
    Nacht = 22:00 desselben Tages bis 07:00 des Folgetages.
    """
    day_start = datetime.combine(d, time(DAY_START_HOUR, 0), tzinfo=TZ)
    night_start = datetime.combine(d, time(NIGHT_START_HOUR, 0), tzinfo=TZ)
    next_day_start = night_start + timedelta(hours=DAY_START_HOUR + (24 - NIGHT_START_HOUR))
    return ((day_start, night_start), (night_start, next_day_start))


def daily_vital_stats(
    session: Session,
    child: Child,
    days: int = 7,
    now: datetime | None = None,
) -> list[VitalDay]:
    """Liefert pro Tag der letzten ``days`` Tage eine VitalDay-Statistik."""
    now = now or datetime.now(TZ)
    today = now.date()
    end_date = today
    start_date = today - timedelta(days=days - 1)

    # Erweiterter Suchbereich: Nacht eines Tages reicht in den Folgetag hinein,
    # also brauchen wir Daten bis +1 Tag.
    start_utc = datetime.combine(start_date, time(DAY_START_HOUR, 0), tzinfo=TZ)
    end_utc = datetime.combine(end_date + timedelta(days=1), time(DAY_START_HOUR, 0), tzinfo=TZ)

    vitals = session.exec(
        select(Vital)
        .where(
            Vital.child_id == child.id,
            Vital.source == "owlet",
            Vital.agg == "avg",
            Vital.kind.in_(VITAL_KINDS),
        )
        .where(Vital.measured_at >= start_utc, Vital.measured_at < end_utc)
        .order_by(Vital.measured_at)
    ).all()

    sessions = session.exec(
        select(SleepSession)
        .where(SleepSession.child_id == child.id)
        .where(
            SleepSession.started_at < end_utc,
            # Nimm auch Sessions die vor start_utc anfingen aber rein ragen:
            # ended_at IS NULL (laufend) ODER ended_at >= start_utc
        )
    ).all()
    sleep_intervals = _build_sleep_intervals([
        s for s in sessions if s.ended_at is None or as_aware(s.ended_at) >= start_utc
    ])

    birth_local_date = (
        as_aware(child.birth_at).astimezone(TZ).date() if child.birth_at else None
    )

    out: list[VitalDay] = []
    cursor = end_date
    while cursor >= start_date:
        (day_win, night_win) = _day_windows(cursor)

        buckets: dict[tuple[str, str], dict] = {
            ("day", "sleep"): {"values": {k: [] for k in VITAL_KINDS}, "win": day_win},
            ("day", "awake"): {"values": {k: [] for k in VITAL_KINDS}, "win": day_win},
            ("night", "sleep"): {"values": {k: [] for k in VITAL_KINDS}, "win": night_win},
            ("night", "awake"): {"values": {k: [] for k in VITAL_KINDS}, "win": night_win},
        }

        for v in vitals:
            dt = as_aware(v.measured_at).astimezone(TZ)
            # Welches Fenster?
            if day_win[0] <= dt < day_win[1]:
                period = "day"
            elif night_win[0] <= dt < night_win[1]:
                period = "night"
            else:
                continue
            state = "sleep" if _is_sleeping(dt, sleep_intervals) else "awake"
            buckets[(period, state)]["values"][v.kind].append(v.value)

        # Schlaf-Minuten pro Tag/Nacht
        sleep_in_day = sum(_overlap_minutes(iv, *day_win) for iv in sleep_intervals)
        sleep_in_night = sum(_overlap_minutes(iv, *night_win) for iv in sleep_intervals)
        total_day_min = int((day_win[1] - day_win[0]).total_seconds() / 60)
        total_night_min = int((night_win[1] - night_win[0]).total_seconds() / 60)

        bucket_list: list[VitalBucket] = []
        for (period, state), data in buckets.items():
            if period == "day":
                dur = sleep_in_day if state == "sleep" else max(0, total_day_min - sleep_in_day)
            else:
                dur = sleep_in_night if state == "sleep" else max(0, total_night_min - sleep_in_night)
            stats_dict = {}
            for kind, vals in data["values"].items():
                if vals:
                    stats_dict[kind] = VitalStats(
                        n=len(vals),
                        avg=sum(vals) / len(vals),
                        min_val=min(vals),
                        max_val=max(vals),
                    )
                else:
                    stats_dict[kind] = VitalStats()
            bucket_list.append(VitalBucket(
                period=period, state=state, duration_min=dur, stats=stats_dict,
            ))

        day_of_life = (cursor - birth_local_date).days + 1 if birth_local_date else 0
        out.append(VitalDay(
            date_iso=cursor.strftime("%Y-%m-%d"),
            weekday=_WEEKDAYS_DE[cursor.weekday()],
            day_of_life=day_of_life,
            buckets=bucket_list,
        ))
        cursor -= timedelta(days=1)

    return out
