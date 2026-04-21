from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Vital(TimestampMixin, table=True):
    __tablename__ = "vitals"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    measured_at: datetime = Field(index=True)
    kind: str = Field(max_length=16)  # temp_body / temp_skin / spo2 / heart_rate
    value: float = Field()
    agg: str | None = Field(default=None, max_length=8)  # instant / min / max / avg
    bucket_min: int | None = Field(default=None)
    source: str = Field(default="manual", max_length=16)  # manual / owlet
    created_by: int | None = Field(default=None, foreign_key="users.id")
