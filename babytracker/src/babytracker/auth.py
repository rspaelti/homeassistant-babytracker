from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from babytracker.config import settings


@dataclass
class CurrentUser:
    name: str
    ha_user_id: str | None
    role: str = "parent"


async def get_current_user(
    x_remote_user_name: str | None = Header(default=None),
    x_remote_user_id: str | None = Header(default=None),
) -> CurrentUser:
    if settings.ingress and x_remote_user_name:
        return CurrentUser(name=x_remote_user_name, ha_user_id=x_remote_user_id)

    if settings.dev_user:
        return CurrentUser(name=settings.dev_user, ha_user_id="dev")

    if not settings.ingress:
        return CurrentUser(name="Dev", ha_user_id="dev")

    raise HTTPException(status_code=401, detail="Nicht eingeloggt")
