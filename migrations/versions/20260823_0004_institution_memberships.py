"""Add institution memberships and richer audit context.

Revision ID: 20260823_0004
Revises: 20260809_0003
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0004"
down_revision: str | None = "20260809_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "institution_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["verified_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution_id", "user_id", name="uq_membership_institution_user"
        ),
    )
    op.create_index(
        "ix_institution_memberships_institution_id",
        "institution_memberships",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        "ix_institution_memberships_role",
        "institution_memberships",
        ["role"],
        unique=False,
    )
    op.create_index(
        "ix_institution_memberships_status",
        "institution_memberships",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_institution_memberships_user_id",
        "institution_memberships",
        ["user_id"],
        unique=False,
    )

    op.add_column("sessions", sa.Column("active_membership_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_sessions_active_membership_id",
        "sessions",
        "institution_memberships",
        ["active_membership_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_sessions_active_membership_id",
        "sessions",
        ["active_membership_id"],
        unique=False,
    )

    op.add_column("audit_events", sa.Column("resource_type", sa.String(100), nullable=True))
    op.add_column("audit_events", sa.Column("resource_id", sa.String(100), nullable=True))
    op.add_column(
        "audit_events",
        sa.Column("outcome", sa.String(32), server_default="success", nullable=False),
    )
    op.add_column("audit_events", sa.Column("reason", sa.String(500), nullable=True))
    op.add_column("audit_events", sa.Column("correlation_id", sa.String(128), nullable=True))
    op.create_index(
        "ix_audit_events_resource_type", "audit_events", ["resource_type"], unique=False
    )
    op.create_index(
        "ix_audit_events_resource_id", "audit_events", ["resource_id"], unique=False
    )
    op.create_index("ix_audit_events_outcome", "audit_events", ["outcome"], unique=False)
    op.create_index(
        "ix_audit_events_correlation_id", "audit_events", ["correlation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_outcome", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_id", table_name="audit_events")
    op.drop_index("ix_audit_events_resource_type", table_name="audit_events")
    op.drop_column("audit_events", "correlation_id")
    op.drop_column("audit_events", "reason")
    op.drop_column("audit_events", "outcome")
    op.drop_column("audit_events", "resource_id")
    op.drop_column("audit_events", "resource_type")

    op.drop_index("ix_sessions_active_membership_id", table_name="sessions")
    op.drop_constraint("fk_sessions_active_membership_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "active_membership_id")

    op.drop_index("ix_institution_memberships_user_id", table_name="institution_memberships")
    op.drop_index("ix_institution_memberships_status", table_name="institution_memberships")
    op.drop_index("ix_institution_memberships_role", table_name="institution_memberships")
    op.drop_index(
        "ix_institution_memberships_institution_id", table_name="institution_memberships"
    )
    op.drop_table("institution_memberships")
