"""add database defaults for communication timestamps

Revision ID: 20260902_0016
Revises: 20260828_0015
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0016"
down_revision: str | None = "20260828_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("communication_preferences", "email_deliveries"):
        for column_name in ("created_at", "updated_at"):
            op.alter_column(
                table_name,
                column_name,
                existing_type=sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                existing_nullable=False,
            )


def downgrade() -> None:
    for table_name in ("communication_preferences", "email_deliveries"):
        for column_name in ("created_at", "updated_at"):
            op.alter_column(
                table_name,
                column_name,
                existing_type=sa.DateTime(timezone=True),
                server_default=None,
                existing_nullable=False,
            )
