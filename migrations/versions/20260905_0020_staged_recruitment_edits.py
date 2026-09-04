"""stage published recruitment edits until drive save

Revision ID: 20260905_0020
Revises: 20260903_0019
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0020"
down_revision: str | None = "20260903_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "placement_drives",
        sa.Column("pending_changes", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "placement_roles",
        sa.Column("pending_changes", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("placement_roles", "pending_changes")
    op.drop_column("placement_drives", "pending_changes")
