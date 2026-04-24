"""add prompt optimization

Revision ID: 20260424_0003
Revises: 20260424_0002
Create Date: 2026-04-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260424_0003"
down_revision: str | None = "20260424_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("optimized_prompt", sa.Text(), nullable=True))
    op.add_column(
        "projects",
        sa.Column(
            "prompt_optimization_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("projects", "prompt_optimization_notes", server_default=None)


def downgrade() -> None:
    op.drop_column("projects", "prompt_optimization_notes")
    op.drop_column("projects", "optimized_prompt")
