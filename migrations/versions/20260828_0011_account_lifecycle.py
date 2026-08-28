"""Add institution-controlled enrollment and account lifecycle records.

Revision ID: 20260828_0011
Revises: 20260824_0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0011"
down_revision: str | None = "20260824_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.add_column(
        "sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_sessions_created_at", "sessions", ["created_at"])

    op.create_table(
        "membership_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("enrollment_id", sa.String(100), nullable=True),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resend_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    for column in (
        "institution_id",
        "email",
        "enrollment_id",
        "role",
        "token_hash",
        "expires_at",
        "created_by_user_id",
    ):
        op.create_index(f"ix_membership_invitations_{column}", "membership_invitations", [column])

    op.create_table(
        "roster_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("total_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invalid_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("invited_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institution_id", "content_sha256", name="uq_roster_import_content"),
    )
    for column in ("institution_id", "created_by_user_id", "status"):
        op.create_index(f"ix_roster_imports_{column}", "roster_imports", [column])

    op.create_table(
        "roster_import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("roster_import_id", sa.Uuid(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("enrollment_id", sa.String(100), nullable=True),
        sa.Column("full_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["roster_import_id"], ["roster_imports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["membership_invitations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("roster_import_id", "row_number", name="uq_roster_import_row_number"),
    )
    op.create_index(
        "ix_roster_import_rows_roster_import_id", "roster_import_rows", ["roster_import_id"]
    )
    op.create_index("ix_roster_import_rows_status", "roster_import_rows", ["status"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    for column in ("user_id", "token_hash", "expires_at", "created_at"):
        op.create_index(f"ix_password_reset_tokens_{column}", "password_reset_tokens", [column])

    op.create_table(
        "mfa_enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_secret", sa.String(512), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_mfa_enrollments_user_id", "mfa_enrollments", ["user_id"], unique=True)

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])
    op.create_index(
        "ix_mfa_recovery_codes_code_hash", "mfa_recovery_codes", ["code_hash"], unique=True
    )

    op.create_table(
        "terms_acceptances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["membership_invitations.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "document_type", "version", name="uq_terms_acceptance"),
    )
    for column in ("user_id", "document_type", "accepted_at"):
        op.create_index(f"ix_terms_acceptances_{column}", "terms_acceptances", [column])


def downgrade() -> None:
    for table in (
        "terms_acceptances",
        "mfa_recovery_codes",
        "mfa_enrollments",
        "password_reset_tokens",
        "roster_import_rows",
        "roster_imports",
        "membership_invitations",
    ):
        op.drop_table(table)
    op.drop_index("ix_sessions_created_at", table_name="sessions")
    op.drop_column("sessions", "mfa_verified_at")
    op.drop_column("sessions", "created_at")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
