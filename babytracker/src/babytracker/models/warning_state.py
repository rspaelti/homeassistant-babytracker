from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel


class WarningState(SQLModel, table=True):
    __tablename__ = "warning_states"

    code: str = Field(primary_key=True, max_length=64)
    child_id: int | None = Field(default=None, foreign_key="children.id", index=True)
    first_seen_at: datetime
    last_seen_at: datetime
    last_notified_at: datetime | None = Field(default=None)
    active: bool = Field(default=True)
    severity: str = Field(default="warn", max_length=16)
    title: str = Field(max_length=200)
    message: str = Field(max_length=500)
