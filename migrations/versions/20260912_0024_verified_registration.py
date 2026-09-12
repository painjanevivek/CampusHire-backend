"""Add verified student and institution registration requests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0024"
down_revision: str | None = "20260905_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:  # type: ignore[type-arg]
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    op.create_table(
        "institution_domains",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["verified_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_institution_domains_domain", "institution_domains", ["domain"], unique=True)
    op.create_index(
        "ix_institution_domains_institution_id", "institution_domains", ["institution_id"]
    )
    op.create_index(
        "ix_institution_domains_verification_status",
        "institution_domains",
        ["verification_status"],
    )

    op.create_table(
        "student_registration_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["membership_invitations.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_student_registration_requests_email", "student_registration_requests", ["email"]
    )
    op.create_index(
        "ix_student_registration_requests_institution_id",
        "student_registration_requests",
        ["institution_id"],
    )
    op.create_index(
        "ix_student_registration_requests_status", "student_registration_requests", ["status"]
    )

    op.create_table(
        "institution_registration_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_name", sa.String(200), nullable=False),
        sa.Column("institution_code", sa.String(32), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("admin_email", sa.String(320), nullable=False),
        sa.Column("duplicate_detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="SET NULL"),
    )
    for column in ("admin_email", "domain", "institution_code", "status"):
        op.create_index(
            f"ix_institution_registration_requests_{column}",
            "institution_registration_requests",
            [column],
        )
    op.create_index(
        "ix_institution_registration_requests_token_hash",
        "institution_registration_requests",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_institution_registration_requests_expires_at",
        "institution_registration_requests",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("institution_registration_requests")
    op.drop_table("student_registration_requests")
    op.drop_table("institution_domains")
