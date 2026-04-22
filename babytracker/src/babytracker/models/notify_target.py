from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NotifyTarget(SQLModel, table=True):
    __tablename__ = "notify_targets"

    id: int | None = Field(default=None, primary_key=True)
    service_name: str = Field(max_length=128, index=True)  # z.B. "mobile_app_renes_iphone"
    label: str = Field(max_length=64)  # "René's iPhone"
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_now)
