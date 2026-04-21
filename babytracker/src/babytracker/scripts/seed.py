"""Legt beim ersten Start des Add-ons einen Parent-User und ein Kind an.

Kind-Daten kommen aus der Add-on-Konfiguration (BT_CHILD_*). Wenn keine
`child_birth_at` gesetzt ist, wird nur ein Parent-User angelegt und das Kind
muss später in der App erfasst werden.
"""

from __future__ import annotations

from sqlmodel import Session, select

from babytracker.config import settings
from babytracker.db import engine
from babytracker.models import Child, Measurement, User


def seed_if_empty() -> None:
    with Session(engine) as session:
        has_user = session.exec(select(User).limit(1)).first()
        if not has_user:
            session.add(User(name="Parent", role="parent"))
            session.commit()
            print("Seed: Parent-User angelegt.")

        has_child = session.exec(select(Child).limit(1)).first()
        if has_child:
            return

        birth_dt = settings.child_birth_dt
        if not birth_dt:
            print("Seed: Kein child_birth_at konfiguriert – kein Kind angelegt.")
            return

        parent = session.exec(select(User).order_by(User.id)).first()

        child = Child(
            name=settings.child_display_name,
            sex=settings.child_sex if settings.child_sex in ("f", "m") else "f",
            birth_at=birth_dt,
            birth_weight_g=settings.child_birth_weight_g or None,
            birth_length_cm=settings.child_birth_length_cm or None,
        )
        session.add(child)
        session.flush()

        if settings.child_birth_weight_g:
            session.add(
                Measurement(
                    child_id=child.id,
                    measured_at=birth_dt,
                    kind="weight",
                    value=float(settings.child_birth_weight_g),
                    source="hospital",
                    created_by=parent.id if parent else None,
                    notes="Geburtsgewicht",
                )
            )
        if settings.child_birth_length_cm:
            session.add(
                Measurement(
                    child_id=child.id,
                    measured_at=birth_dt,
                    kind="length",
                    value=float(settings.child_birth_length_cm),
                    source="hospital",
                    created_by=parent.id if parent else None,
                    notes="Geburtslänge",
                )
            )

        session.commit()
        print(f"Seed: Kind '{child.name}' mit Geburtsdaten angelegt.")


if __name__ == "__main__":
    seed_if_empty()
