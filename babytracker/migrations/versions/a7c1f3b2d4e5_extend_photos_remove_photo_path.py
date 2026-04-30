"""extend photos with EXIF/dimensions, remove unused photo_path columns

Revision ID: a7c1f3b2d4e5
Revises: 0f1dce8f5d42
Create Date: 2026-04-30 12:00:00+02:00

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "a7c1f3b2d4e5"
down_revision: str | Sequence[str] | None = "0f1dce8f5d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("original_path", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True)
        )
        batch_op.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("height", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("gps_lat", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("gps_lng", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("camera_make", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("camera_model", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True)
        )

    with op.batch_alter_table("health_events", schema=None) as batch_op:
        batch_op.drop_column("photo_path")

    with op.batch_alter_table("mother_logs", schema=None) as batch_op:
        batch_op.drop_column("photo_path")


def downgrade() -> None:
    with op.batch_alter_table("mother_logs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("photo_path", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True)
        )

    with op.batch_alter_table("health_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("photo_path", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True)
        )

    with op.batch_alter_table("photos", schema=None) as batch_op:
        batch_op.drop_column("camera_model")
        batch_op.drop_column("camera_make")
        batch_op.drop_column("gps_lng")
        batch_op.drop_column("gps_lat")
        batch_op.drop_column("size_bytes")
        batch_op.drop_column("height")
        batch_op.drop_column("width")
        batch_op.drop_column("original_path")
