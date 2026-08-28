"""Add student application withdrawal and appeal lifecycle records.

Revision ID: 20260828_0012
Revises: 20260828_0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0012"
down_revision: str | None = "20260828_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("decision_snapshot", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "applications", sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("applications", sa.Column("withdrawal_reason", sa.String(500), nullable=True))
    op.create_table(
        "application_appeals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="submitted", nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("supporting_evidence", sa.JSON(), nullable=False),
        sa.Column("administrator_response", sa.String(2000), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "application_id", "idempotency_key", name="uq_application_appeal_idempotency"
        ),
    )
    for column in ("institution_id", "application_id", "student_user_id", "kind", "status"):
        op.create_index(f"ix_application_appeals_{column}", "application_appeals", [column])


def downgrade() -> None:
    op.drop_table("application_appeals")
    op.drop_column("applications", "withdrawal_reason")
    op.drop_column("applications", "withdrawn_at")
    op.drop_column("applications", "decision_snapshot")
