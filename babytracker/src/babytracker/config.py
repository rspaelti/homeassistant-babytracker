from __future__ import annotations

import os
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

    ha_url: str | None = None
    ha_token: str | None = None

    ingress: bool = False
    dev_user: str | None = None

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


settings = Settings()

os.environ.setdefault("BT_DB_PATH", str(settings.db_path))
for p in (settings.data_dir, settings.photos_dir, settings.backups_dir):
    p.mkdir(parents=True, exist_ok=True)
