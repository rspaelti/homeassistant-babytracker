from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None, index=True)
