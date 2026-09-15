"""Require direct-provisioned staff to accept terms on first sign-in."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0030"
down_revision: str | None = "20260914_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "requires_terms_acceptance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "requires_terms_acceptance")
