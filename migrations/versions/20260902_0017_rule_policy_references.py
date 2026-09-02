"""snapshot policy provenance on eligibility rule versions

Revision ID: 20260902_0017
Revises: 20260902_0016
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0017"
down_revision: str | None = "20260902_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eligibility_rule_sets",
        sa.Column(
            "policy_references",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("eligibility_rule_sets", "policy_references")
