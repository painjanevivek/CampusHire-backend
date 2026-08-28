"""Add institution controls for evidence-led student workflows.

Revision ID: 20260828_0013
Revises: 20260828_0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0013"
down_revision: str | None = "20260828_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "institutions",
        sa.Column("roadmaps_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "institutions",
        sa.Column("timezone", sa.String(64), server_default="Asia/Kolkata", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("institutions", "timezone")
    op.drop_column("institutions", "roadmaps_enabled")
