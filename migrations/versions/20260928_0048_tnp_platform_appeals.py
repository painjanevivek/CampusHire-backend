"""Persist officer-to-platform-admin appeals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0048"
down_revision: str | None = "20260928_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tnp_platform_appeals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "institution_id",
            sa.Uuid(),
            sa.ForeignKey("institutions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "submitted_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_tnp_platform_appeals_institution_id", "tnp_platform_appeals", ["institution_id"]
    )
    op.create_index(
        "ix_tnp_platform_appeals_submitted_by_user_id",
        "tnp_platform_appeals",
        ["submitted_by_user_id"],
    )
    op.create_index("ix_tnp_platform_appeals_status", "tnp_platform_appeals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tnp_platform_appeals_status", table_name="tnp_platform_appeals")
    op.drop_index("ix_tnp_platform_appeals_submitted_by_user_id", table_name="tnp_platform_appeals")
    op.drop_index("ix_tnp_platform_appeals_institution_id", table_name="tnp_platform_appeals")
    op.drop_table("tnp_platform_appeals")
