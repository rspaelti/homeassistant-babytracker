from __future__ import annotations

from sqlmodel import Field, SQLModel


class WarningRuleConfig(SQLModel, table=True):
    __tablename__ = "warning_rule_config"

    code: str = Field(primary_key=True, max_length=64)
    enabled: bool = Field(default=True)
    push_enabled: bool = Field(default=True)
