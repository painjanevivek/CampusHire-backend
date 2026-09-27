"""Record whether a placement role is paid separately from its stipend text."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0046"
down_revision: str | None = "20260926_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing roles keep an unknown payment status; a free-text salary value
    # alone is insufficient evidence to classify them as paid or unpaid.
    op.add_column("placement_roles", sa.Column("is_paid", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("placement_roles", "is_paid")
