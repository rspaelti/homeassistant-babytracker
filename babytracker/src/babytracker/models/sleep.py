from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class SleepSession(TimestampMixin, table=True):
    __tablename__ = "sleep_sessions"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    started_at: datetime = Field(index=True)
    ended_at: datetime | None = Field(default=None)
    location: str | None = Field(default=None, max_length=32)
    owlet_worn: bool = Field(default=False)
    notes: str | None = Field(default=None, max_length=500)
    created_by: int | None = Field(default=None, foreign_key="users.id")
