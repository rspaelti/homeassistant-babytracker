from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from babytracker.config import settings

_engine_kwargs = {
    "connect_args": {"check_same_thread": False},
    "echo": False,
}
if settings.db_path.as_posix() == ":memory:":
    _engine_kwargs["poolclass"] = StaticPool

engine = create_engine(settings.db_url, **_engine_kwargs)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
