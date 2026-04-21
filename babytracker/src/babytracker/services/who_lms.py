"""WHO-Perzentilen-Berechnung basierend auf den LMS-Parametern.

Formeln:
    Z = ((X/M)^L - 1) / (L*S)            wenn L != 0
    Z = ln(X/M) / S                      wenn L = 0
    P = Phi(Z) * 100                     (Normal-CDF)

Für die Umkehrung (Perzentil → X) analog aus den LMS-Werten.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

from sqlmodel import Session, select

from babytracker.db import engine
from babytracker.models import WhoLms

REFERENCE_PERCENTILES = (3, 15, 50, 85, 97)


@dataclass(frozen=True)
class LMS:
    L: float
    M: float
    S: float


def normal_cdf(z: float) -> float:
    """Kumulative Standard-Normalverteilung."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def normal_ppf(p: float) -> float:
    """Inverse Standard-Normalverteilung für p in (0,1).

    Implementierung nach Beasley-Springer-Moro.
    Präzision für p in (1e-6, 1-1e-6) ausreichend.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"p muss in (0,1) sein, nicht {p}")

    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838,
        -2.549732539343734,
        4.374664141464968,
        2.938163982698783,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996,
        3.754408661907416,
    ]

    p_low = 0.02425
    p_high = 1 - p_low

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(
        ((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]
    ) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def z_from_value(value: float, lms: LMS) -> float:
    if lms.L == 0:
        return math.log(value / lms.M) / lms.S
    return ((value / lms.M) ** lms.L - 1.0) / (lms.L * lms.S)


def value_from_z(z: float, lms: LMS) -> float:
    if lms.L == 0:
        return lms.M * math.exp(lms.S * z)
    return lms.M * (1.0 + lms.L * lms.S * z) ** (1.0 / lms.L)


def percentile_from_z(z: float) -> float:
    return normal_cdf(z) * 100.0


@cache
def _lms_cache_key(indicator: str, sex: str) -> dict[int, LMS]:
    with Session(engine) as session:
        rows = session.exec(
            select(WhoLms).where(WhoLms.indicator == indicator, WhoLms.sex == sex)
        ).all()
    return {r.age_days: LMS(L=r.L, M=r.M, S=r.S) for r in rows}


def get_lms(indicator: str, sex: str, age_days: float) -> LMS:
    """Liefert LMS-Parameter für `age_days`.

    Zwischen ganztägigen Einträgen wird linear interpoliert.
    Ausserhalb des Bereichs wird auf Min/Max geclamped.
    """
    table = _lms_cache_key(indicator, sex)
    if not table:
        raise ValueError(f"Keine WHO-Daten für {indicator}/{sex}")

    day_lo = int(math.floor(age_days))
    day_hi = day_lo + 1

    if day_lo in table and day_hi not in table:
        return table[day_lo]
    if day_lo in table and day_hi in table:
        t = age_days - day_lo
        a, b = table[day_lo], table[day_hi]
        return LMS(
            L=a.L + t * (b.L - a.L),
            M=a.M + t * (b.M - a.M),
            S=a.S + t * (b.S - a.S),
        )
    max_day = max(table)
    min_day = min(table)
    if age_days < min_day:
        return table[min_day]
    return table[max_day]


def reference_lines(indicator: str, sex: str, days: list[float]) -> dict[int, list[float]]:
    """Für jeden Ziel-Perzentil (P3/15/50/85/97) die Werte an den `days`-Punkten."""
    result: dict[int, list[float]] = {p: [] for p in REFERENCE_PERCENTILES}
    for d in days:
        lms = get_lms(indicator, sex, d)
        for p in REFERENCE_PERCENTILES:
            z = normal_ppf(p / 100.0)
            result[p].append(value_from_z(z, lms))
    return result


def evaluate(indicator: str, sex: str, age_days: float, value: float) -> tuple[float, float]:
    """Gibt (z_score, percentile) für einen Messwert zurück."""
    lms = get_lms(indicator, sex, age_days)
    z = z_from_value(value, lms)
    return z, percentile_from_z(z)
