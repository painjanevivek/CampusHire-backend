"""Add immutable resume versions.

Revision ID: 20260809_0003
Revises: 20260809_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0003"
down_revision: str | None = "20260809_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("original_name", sa.String(200), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
        sa.UniqueConstraint("user_id", "checksum", name="uq_resume_user_checksum"),
    )
    op.create_index("ix_resume_versions_checksum", "resume_versions", ["checksum"])
    op.create_index("ix_resume_versions_status", "resume_versions", ["status"])
    op.create_index("ix_resume_versions_user_id", "resume_versions", ["user_id"])


def downgrade() -> None:
    op.drop_table("resume_versions")
