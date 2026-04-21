from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Feeding(TimestampMixin, table=True):
    __tablename__ = "feedings"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    started_at: datetime = Field(index=True)
    ended_at: datetime | None = Field(default=None)
    kind: str = Field(max_length=16)  # breast / bottle / solid
    breast_side: str | None = Field(default=None, max_length=8)  # left / right / both
    duration_left_min: int | None = Field(default=None)
    duration_right_min: int | None = Field(default=None)
    bottle_type: str | None = Field(default=None, max_length=16)
    bottle_offered_ml: int | None = Field(default=None)
    bottle_taken_ml: int | None = Field(default=None)
    spit_up: bool = Field(default=False)
    spit_up_amount: str | None = Field(default=None, max_length=16)
    notes: str | None = Field(default=None, max_length=500)
    created_by: int | None = Field(default=None, foreign_key="users.id")
