from __future__ import annotations

from sqlmodel import Field, SQLModel


class FeedingSettings(SQLModel, table=True):
    """Einstellungen für die Trinkmengen-Berechnung. Single-Row-Tabelle (id=1).

    Vier Lebensphasen mit je einem ml/min-Wert. Die ersten drei haben ein
    oberes Tages-Limit (``phaseN_max_day``); Phase 4 hat keine Obergrenze und
    gilt für alles ab ``phase3_max_day + 1``.
    """

    __tablename__ = "feeding_settings"

    id: int = Field(default=1, primary_key=True)

    phase1_max_day: int = Field(default=7)
    phase1_ml_per_min: float = Field(default=1.0)

    phase2_max_day: int = Field(default=21)
    phase2_ml_per_min: float = Field(default=2.5)

    phase3_max_day: int = Field(default=90)
    phase3_ml_per_min: float = Field(default=3.5)

    phase4_ml_per_min: float = Field(default=4.0)
