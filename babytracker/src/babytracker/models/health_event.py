from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class HealthEvent(TimestampMixin, table=True):
    __tablename__ = "health_events"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    recorded_at: datetime = Field(index=True)
    category: str = Field(max_length=32)  # jaundice / umbilical / skin / crying / other
    score: int | None = Field(default=None)
    status: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=1000)
    created_by: int | None = Field(default=None, foreign_key="users.id")
