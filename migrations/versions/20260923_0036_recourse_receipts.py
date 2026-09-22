"""Add truthful privacy receipts and appeal resolution effects."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0036"
down_revision: str | None = "20260923_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("privacy_requests", sa.Column("resolution_effect", sa.String(length=80)))
    op.add_column(
        "privacy_requests",
        sa.Column(
            "processing_receipt",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.add_column("application_appeals", sa.Column("resolution_effect", sa.String(length=80)))


def downgrade() -> None:
    op.drop_column("application_appeals", "resolution_effect")
    op.drop_column("privacy_requests", "processing_receipt")
    op.drop_column("privacy_requests", "resolution_effect")
