"""Add progressive student profiles.

Revision ID: 20260809_0002
Revises: 20260809_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0002"
down_revision: str | None = "20260809_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=True),
        sa.Column("institution_name", sa.String(200), nullable=True),
        sa.Column("prn", sa.String(64), nullable=True),
        sa.Column("department", sa.String(120), nullable=True),
        sa.Column("academic_year", sa.String(32), nullable=True),
        sa.Column("phone", sa.String(24), nullable=True),
        sa.Column("education", sa.JSON(), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("target_roles", sa.JSON(), nullable=False),
        sa.Column("external_links", sa.JSON(), nullable=False),
        sa.Column("onboarding_step", sa.Integer(), nullable=False),
        sa.Column("readiness", sa.Integer(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_student_profiles_prn", "student_profiles", ["prn"])
    op.create_index("ix_student_profiles_user_id", "student_profiles", ["user_id"])


def downgrade() -> None:
    op.drop_table("student_profiles")
