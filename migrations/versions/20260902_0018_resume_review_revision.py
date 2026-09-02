"""add optimistic revision to resume review state

Revision ID: 20260902_0018
Revises: 20260902_0017
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0018"
down_revision: str | None = "20260902_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resume_versions",
        sa.Column("review_revision", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("resume_versions", "review_revision")
