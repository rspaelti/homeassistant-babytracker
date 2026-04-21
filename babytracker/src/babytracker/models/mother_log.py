from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class MotherLog(TimestampMixin, table=True):
    __tablename__ = "mother_logs"

    id: int | None = Field(default=None, primary_key=True)
    mother_id: int = Field(foreign_key="users.id", index=True)
    logged_at: datetime = Field(index=True)
    category: str = Field(max_length=32)
    value_num: float | None = Field(default=None)
    value_text: str | None = Field(default=None, max_length=500)
    photo_path: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=1000)
