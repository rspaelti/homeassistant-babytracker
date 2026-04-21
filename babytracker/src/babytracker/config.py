from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BT_", extra="ignore")

    db_path: Path = Field(default=Path("./dev.sqlite3"))
    data_dir: Path = Field(default=Path("./dev-data"))
    photos_dir: Path = Field(default=Path("./dev-data/photos"))
    backups_dir: Path = Field(default=Path("./dev-data/backups"))
    who_dir: Path = Field(default=Path("./data/who"))

    timezone: str = "Europe/Zurich"
    owlet_prefix: str = "sensor.dream_sock_"
    log_level: str = "info"

    child_name: str = ""
    child_sex: str = "f"
    child_birth_at: str = ""
    child_birth_weight_g: int = 0
    child_birth_length_cm: float = 0.0

    ha_url: str | None = None
    ha_token: str | None = None

    ingress: bool = False
    dev_user: str | None = None

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def child_birth_dt(self) -> datetime | None:
        if not self.child_birth_at:
            return None
        try:
            return datetime.fromisoformat(self.child_birth_at)
        except ValueError:
            return None

    @property
    def child_display_name(self) -> str:
        return self.child_name or "Baby"


settings = Settings()

os.environ.setdefault("BT_DB_PATH", str(settings.db_path))
for p in (settings.data_dir, settings.photos_dir, settings.backups_dir):
    p.mkdir(parents=True, exist_ok=True)
