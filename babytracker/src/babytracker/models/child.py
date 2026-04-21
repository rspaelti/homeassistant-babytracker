from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Child(TimestampMixin, table=True):
    __tablename__ = "children"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=64, index=True)
    sex: str = Field(max_length=1)  # 'f' / 'm'
    birth_at: datetime = Field(index=True)
    birth_weight_g: int | None = Field(default=None)
    birth_length_cm: float | None = Field(default=None)
    birth_head_cm: float | None = Field(default=None)
    gestational_weeks: float | None = Field(default=None)
    active: bool = Field(default=True)
