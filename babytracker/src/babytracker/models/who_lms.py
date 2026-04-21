from __future__ import annotations

from sqlmodel import Field, SQLModel


class WhoLms(SQLModel, table=True):
    __tablename__ = "who_lms"

    id: int | None = Field(default=None, primary_key=True)
    indicator: str = Field(max_length=16, index=True)  # weight / length / head
    sex: str = Field(max_length=1, index=True)  # f / m
    age_days: int = Field(index=True)
    L: float = Field()
    M: float = Field()
    S: float = Field()
