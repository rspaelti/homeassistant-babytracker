from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from babytracker.models import Child, Measurement
from babytracker.services.who_lms import (
    REFERENCE_PERCENTILES,
    evaluate,
    reference_lines,
)

KIND_UNITS = {"weight": "g", "length": "cm", "head": "cm"}
KIND_LABELS = {"weight": "Gewicht", "length": "Länge", "head": "Kopfumfang"}


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_days(child: Child, at: datetime) -> float:
    delta = _as_utc(at) - _as_utc(child.birth_at)
    return delta.total_seconds() / 86400.0


def who_value_unit(kind: str, value: float) -> float:
    """Von DB-Einheit (g, cm) zu WHO-Einheit (kg, cm)."""
    return value / 1000.0 if kind == "weight" else value


def display_value(kind: str, value: float) -> str:
    if kind == "weight":
        return f"{int(round(value))} g"
    return f"{value:.1f} cm"


@dataclass
class ChartPoint:
    age_days: float
    value: float  # in WHO-Einheit (kg, cm)
    measured_at: datetime
    z: float
    percentile: float
    source: str


@dataclass
class ChartData:
    indicator: str
    unit: str
    label: str
    points: list[ChartPoint]
    reference_days: list[float]
    reference_lines: dict[int, list[float]]
    reference_percentiles: tuple[int, ...]


def build_chart(
    session: Session,
    child: Child,
    kind: str,
    reference_horizon_days: int | None = None,
) -> ChartData:
    measurements = session.exec(
        select(Measurement)
        .where(Measurement.child_id == child.id, Measurement.kind == kind)
        .order_by(Measurement.measured_at)
    ).all()

    points: list[ChartPoint] = []
    for m in measurements:
        d = age_days(child, m.measured_at)
        who_val = who_value_unit(kind, m.value)
        z, p = evaluate(kind, child.sex, d, who_val)
        points.append(
            ChartPoint(
                age_days=d,
                value=who_val,
                measured_at=m.measured_at,
                z=z,
                percentile=p,
                source=m.source,
            )
        )

    if reference_horizon_days is None:
        if points:
            reference_horizon_days = max(90, int(points[-1].age_days) + 30)
        else:
            reference_horizon_days = 90
    reference_horizon_days = min(reference_horizon_days, 1855)

    if reference_horizon_days <= 90:
        step = 1
    elif reference_horizon_days <= 365:
        step = 2
    else:
        step = 7
    days = list(range(0, reference_horizon_days + 1, step))
    lines = reference_lines(kind, child.sex, [float(d) for d in days])

    return ChartData(
        indicator=kind,
        unit=KIND_UNITS[kind],
        label=KIND_LABELS[kind],
        points=points,
        reference_days=[float(d) for d in days],
        reference_lines=lines,
        reference_percentiles=REFERENCE_PERCENTILES,
    )
