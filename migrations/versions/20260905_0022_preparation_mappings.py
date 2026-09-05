"""Store explicit reviewed requirement mappings without inventing approved content."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0022"
down_revision: str | None = "20260905_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviewed_preparation_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), sa.ForeignKey("institutions.id"), nullable=False),
        sa.Column("template_id", sa.Uuid(), sa.ForeignKey("roadmap_templates.id"), nullable=False),
        sa.Column("node_key", sa.String(80), nullable=False),
        sa.Column("requirement", sa.String(160), nullable=False),
        sa.Column(
            "reviewed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="approved"),
    )
    op.create_index(
        "ix_reviewed_preparation_mappings_institution_id",
        "reviewed_preparation_mappings",
        ["institution_id"],
    )


def downgrade() -> None:
    op.drop_table("reviewed_preparation_mappings")
