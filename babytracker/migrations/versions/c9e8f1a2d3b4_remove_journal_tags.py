"""remove unused tags column from journal_entries

Revision ID: c9e8f1a2d3b4
Revises: a7c1f3b2d4e5
Create Date: 2026-04-30 16:00:00+02:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "c9e8f1a2d3b4"
down_revision: str | Sequence[str] | None = "a7c1f3b2d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("journal_entries", schema=None) as batch_op:
        batch_op.drop_column("tags")


def downgrade() -> None:
    with op.batch_alter_table("journal_entries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("tags", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True)
        )
