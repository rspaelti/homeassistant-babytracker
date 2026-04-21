from __future__ import annotations

from datetime import date

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Milestone(TimestampMixin, table=True):
    __tablename__ = "milestones"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    observed_at: date = Field(index=True)
    name: str = Field(max_length=64)
    notes: str | None = Field(default=None, max_length=500)
    created_by: int | None = Field(default=None, foreign_key="users.id")
