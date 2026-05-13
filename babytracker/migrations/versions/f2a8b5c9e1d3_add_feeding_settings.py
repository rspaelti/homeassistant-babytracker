"""add feeding_settings table

Revision ID: f2a8b5c9e1d3
Revises: c9e8f1a2d3b4
Create Date: 2026-05-13 12:00:00.000000+02:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a8b5c9e1d3"
down_revision: str | Sequence[str] | None = "c9e8f1a2d3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feeding_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("phase1_max_day", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("phase1_ml_per_min", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("phase2_max_day", sa.Integer(), nullable=False, server_default="21"),
        sa.Column("phase2_ml_per_min", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("phase3_max_day", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("phase3_ml_per_min", sa.Float(), nullable=False, server_default="3.5"),
        sa.Column("phase4_ml_per_min", sa.Float(), nullable=False, server_default="4.0"),
    )
    # Seed: einzige Row mit Defaults
    op.execute(
        "INSERT INTO feeding_settings "
        "(id, phase1_max_day, phase1_ml_per_min, phase2_max_day, phase2_ml_per_min, "
        " phase3_max_day, phase3_ml_per_min, phase4_ml_per_min) "
        "VALUES (1, 7, 1.0, 21, 2.5, 90, 3.5, 4.0)"
    )


def downgrade() -> None:
    op.drop_table("feeding_settings")
