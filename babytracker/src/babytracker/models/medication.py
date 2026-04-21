from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Medication(TimestampMixin, table=True):
    __tablename__ = "medications"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    given_at: datetime = Field(index=True)
    med_name: str = Field(max_length=64)
    dose_value: float = Field()
    dose_unit: str = Field(max_length=16)
    route: str = Field(max_length=16)  # oral / injection / topical
    notes: str | None = Field(default=None, max_length=500)
    created_by: int | None = Field(default=None, foreign_key="users.id")
