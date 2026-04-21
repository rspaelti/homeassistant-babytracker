from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Appointment(TimestampMixin, table=True):
    __tablename__ = "appointments"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int | None = Field(default=None, foreign_key="children.id", index=True)
    mother_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    scheduled_at: datetime = Field(index=True)
    kind: str = Field(max_length=32)
    label: str = Field(max_length=128)
    location: str | None = Field(default=None, max_length=128)
    done_at: datetime | None = Field(default=None)
    notes: str | None = Field(default=None, max_length=1000)
    reaction: str | None = Field(default=None, max_length=500)
