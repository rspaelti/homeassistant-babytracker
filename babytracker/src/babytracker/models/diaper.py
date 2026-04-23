from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Diaper(TimestampMixin, table=True):
    __tablename__ = "diapers"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    changed_at: datetime = Field(index=True)
    pee: bool = Field(default=False)
    stool: bool = Field(default=False)
    pee_intensity: str | None = Field(default=None, max_length=16)
    pee_amount: str | None = Field(default=None, max_length=16)  # light / normal / heavy
    stool_color: str | None = Field(default=None, max_length=16)
    stool_consistency: str | None = Field(default=None, max_length=16)
    stool_amount: str | None = Field(default=None, max_length=16)  # light / normal / heavy
    notes: str | None = Field(default=None, max_length=500)
    created_by: int | None = Field(default=None, foreign_key="users.id")
