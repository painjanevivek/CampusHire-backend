"""add bounded MFA challenge attempts

Revision ID: 20260828_0015
Revises: 20260828_0014
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0015"
down_revision: str | None = "20260828_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("mfa_failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mfa_enrollments",
        sa.Column("pending_encrypted_secret", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "mfa_enrollments",
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mfa_enrollments",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )

    deliveries = sa.table(
        "email_deliveries",
        sa.column("template_key", sa.String()),
        sa.column("template_variables", sa.JSON()),
        sa.column("status", sa.String()),
        sa.column("safe_error_code", sa.String()),
    )
    sensitive = deliveries.c.template_key.in_(["invitation", "password_reset"])
    retryable = deliveries.c.status.in_(["queued", "retrying", "sending"])
    op.execute(
        deliveries.update()
        .where(sensitive, retryable)
        .values(status="failed", safe_error_code="sensitive_payload_migration_required")
    )
    op.execute(deliveries.update().where(sensitive).values(template_variables={}))


def downgrade() -> None:
    op.drop_column("mfa_enrollments", "locked_until")
    op.drop_column("mfa_enrollments", "failed_attempts")
    op.drop_column("mfa_enrollments", "pending_encrypted_secret")
    op.drop_column("sessions", "mfa_failed_attempts")
