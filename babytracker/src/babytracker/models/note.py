from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Note(TimestampMixin, table=True):
    __tablename__ = "notes"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int | None = Field(default=None, foreign_key="children.id", index=True)
    mother_id: int | None = Field(default=None, foreign_key="users.id", index=True)
    logged_at: datetime = Field(index=True)
    body: str = Field()
    tags: str | None = Field(default=None, max_length=500)  # JSON-Array
