from __future__ import annotations

from datetime import datetime

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class Photo(TimestampMixin, table=True):
    __tablename__ = "photos"

    id: int | None = Field(default=None, primary_key=True)
    taken_at: datetime = Field(index=True)
    rel_path: str = Field(max_length=255)
    mime: str = Field(default="image/jpeg", max_length=32)
    uploader_user_id: int | None = Field(default=None, foreign_key="users.id")
    linked_table: str | None = Field(default=None, max_length=32)
    linked_id: int | None = Field(default=None)
    visibility: str = Field(default="family", max_length=16)
    thumb_path: str | None = Field(default=None, max_length=255)
