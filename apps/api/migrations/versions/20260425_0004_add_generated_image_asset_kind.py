"""add generated image asset kind

Revision ID: 20260425_0004
Revises: 20260424_0003
Create Date: 2026-04-25 00:00:00.000000
"""

from alembic import op


revision = "20260425_0004"
down_revision = "20260424_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE asset_kind ADD VALUE IF NOT EXISTS 'generated_image'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely without recreating the type.
    pass
