from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class JournalEntry(TimestampMixin, table=True):
    __tablename__ = "journal_entries"

    id: int | None = Field(default=None, primary_key=True)
    child_id: int | None = Field(default=None, foreign_key="children.id", index=True)
    author_user_id: int = Field(foreign_key="users.id")
    happened_at: datetime = Field(index=True)
    title: str = Field(max_length=200)
    body: str = Field()
    mood: str | None = Field(default=None, max_length=16)
    location: str | None = Field(default=None, max_length=128)
    tags: str | None = Field(default=None, max_length=500)
    visibility: str = Field(default="family", max_length=16)
