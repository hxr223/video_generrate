"""add optional shot binding for assets

Revision ID: 20260425_0005
Revises: 20260425_0004
Create Date: 2026-04-25 00:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260425_0005"
down_revision: str | None = "20260425_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("shot_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_assets_shot_id", "assets", ["shot_id"])
    op.create_foreign_key(
        "fk_assets_shot_id_shots",
        "assets",
        "shots",
        ["shot_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_assets_shot_id_shots", "assets", type_="foreignkey")
    op.drop_index("ix_assets_shot_id", table_name="assets")
    op.drop_column("assets", "shot_id")
