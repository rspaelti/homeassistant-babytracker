"""Legt beim ersten Start einen Parent-User an, falls noch keiner existiert.

Das Kind wird via Setup-UI (/setup/child) in der App selbst angelegt.
"""

from __future__ import annotations

from sqlmodel import Session, select

from babytracker.db import engine
from babytracker.models import User


def seed_if_empty() -> None:
    with Session(engine) as session:
        if session.exec(select(User).limit(1)).first():
            return
        session.add(User(name="Parent", role="parent"))
        session.commit()
        print("Seed: Parent-User angelegt.")


if __name__ == "__main__":
    seed_if_empty()
