from __future__ import annotations

from sqlmodel import Field

from babytracker.models._base import TimestampMixin


class User(TimestampMixin, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=64, index=True)
    role: str = Field(default="parent", max_length=16)  # parent / family / readonly
    ha_user_id: str | None = Field(default=None, max_length=64, index=True)
    external_token: str | None = Field(default=None, max_length=128)
    active: bool = Field(default=True)
