"""create projects

Revision ID: 20260424_0001
Revises:
Create Date: 2026-04-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260424_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    project_status = postgresql.ENUM(
        "draft",
        "planning",
        "generating",
        "assembling",
        "rendering",
        "completed",
        "failed",
        name="project_status",
    )
    project_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("target_duration", sa.Integer(), nullable=False),
        sa.Column("target_ratio", sa.String(length=16), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("style", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=80), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft",
                "planning",
                "generating",
                "assembling",
                "rendering",
                "completed",
                "failed",
                name="project_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(length=120), nullable=True),
        sa.Column("final_video_url", sa.Text(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("subtitle_url", sa.Text(), nullable=True),
        sa.Column("script_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_created_at", "projects", ["created_at"])
    op.create_index("ix_projects_status", "projects", ["status"])


def downgrade() -> None:
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_index("ix_projects_created_at", table_name="projects")
    op.drop_table("projects")
    postgresql.ENUM(name="project_status").drop(op.get_bind(), checkfirst=True)
