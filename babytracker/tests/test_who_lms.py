"""Smoke-Tests für die WHO-Perzentilen-Berechnung.

Reale Referenzwerte aus den WHO-Expanded-Tables (verifiziert):
- Mädchen, 0 Tage, 3.820 kg → Z ~+1.20, Perzentil ~88
- Mädchen, 0 Tage, 55 cm → Z ~+3.14, Perzentil >99.9
- Jungen, 0 Tage, 3.3464 kg (Median) → Z ~0, Perzentil ~50
"""

from __future__ import annotations

import math

import pytest

from babytracker.services.who_lms import (
    LMS,
    evaluate,
    normal_cdf,
    normal_ppf,
    value_from_z,
    z_from_value,
)


def test_normal_cdf_known_values():
    assert math.isclose(normal_cdf(0.0), 0.5, abs_tol=1e-9)
    assert math.isclose(normal_cdf(1.0), 0.8413, abs_tol=1e-3)
    assert math.isclose(normal_cdf(-1.0), 0.1587, abs_tol=1e-3)


def test_normal_ppf_roundtrip():
    for p in (0.03, 0.15, 0.5, 0.85, 0.97):
        z = normal_ppf(p)
        assert math.isclose(normal_cdf(z), p, abs_tol=1e-3)


def test_lms_roundtrip():
    lms = LMS(L=0.3809, M=3.2322, S=0.14171)  # wfa_girls Tag 0
    for z in (-2.0, -1.0, 0.0, 1.0, 2.0):
        x = value_from_z(z, lms)
        z_back = z_from_value(x, lms)
        assert math.isclose(z, z_back, abs_tol=1e-6)


def test_girl_weight_3820g_day0():
    z, p = evaluate("weight", "f", age_days=0, value=3.820)
    assert 1.0 < z < 1.3, f"z={z}"
    assert 84 < p < 90, f"p={p}"


def test_girl_length_55cm_day0():
    z, p = evaluate("length", "f", age_days=0, value=55.0)
    assert 2.9 < z < 3.3, f"z={z}"  # 55 cm ist sehr lang (WHO-Median 49.1 cm)
    assert p > 99.5, f"p={p}"


def test_boy_median_weight_day_0():
    z, p = evaluate("weight", "m", age_days=0, value=3.3464)  # M für Jungen Tag 0
    assert abs(z) < 0.01
    assert abs(p - 50) < 0.5


@pytest.mark.parametrize("indicator,sex", [
    ("weight", "f"), ("weight", "m"),
    ("length", "f"), ("length", "m"),
    ("head", "f"), ("head", "m"),
])
def test_all_indicators_loaded(indicator, sex):
    """Stichprobe: Tag 0, Tag 365, Tag 1000 liefern sinnvolle Werte."""
    for day in (0, 365, 1000):
        z, p = evaluate(indicator, sex, day, value=_reasonable_value(indicator, day))
        assert -5 < z < 5, f"{indicator}/{sex}/d{day}: z={z}"
        assert 0 < p < 100


def _reasonable_value(indicator: str, day: int) -> float:
    """Grobe Median-Schätzung zur Sanity-Prüfung."""
    if indicator == "weight":
        return 3.3 + day * 0.012
    if indicator == "length":
        return 50 + day * 0.04
    return 34 + day * 0.02
