from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class MeasurementKind(str, Enum):
    weight = "weight"  # in Gramm
    length = "length"  # in cm
    head = "head"  # in cm (Kopfumfang)


class Measurement(TimestampMixin, table=True):
    __tablename__ = "measurements"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    measured_at: datetime = Field(index=True)
    kind: str = Field(max_length=16, index=True)
    value: float = Field()
    source: str = Field(default="home", max_length=16)  # home / doctor / hospital
    created_by: int | None = Field(default=None, foreign_key="users.id")
    notes: str | None = Field(default=None, max_length=500)
