"""Add durable leases, cancellation, and operational job history.

Revision ID: 20260824_0009
Revises: 20260824_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0009"
down_revision: str | None = "20260824_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resume_processing_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "resume_processing_jobs", sa.Column("claimed_by", sa.String(80), nullable=True)
    )
    op.add_column(
        "resume_processing_jobs",
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "resume_processing_jobs", sa.Column("duration_ms", sa.Integer(), nullable=True)
    )
    op.create_index(
        "ix_resume_processing_jobs_lease_expires_at",
        "resume_processing_jobs",
        ["lease_expires_at"],
    )
    op.create_table(
        "resume_job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(80), nullable=True),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["resume_processing_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("job_id", "event_type", "status", "correlation_id", "occurred_at"):
        op.create_index(f"ix_resume_job_events_{column}", "resume_job_events", [column])


def downgrade() -> None:
    op.drop_table("resume_job_events")
    op.drop_index(
        "ix_resume_processing_jobs_lease_expires_at", table_name="resume_processing_jobs"
    )
    op.drop_column("resume_processing_jobs", "duration_ms")
    op.drop_column("resume_processing_jobs", "cancellation_requested_at")
    op.drop_column("resume_processing_jobs", "claimed_by")
    op.drop_column("resume_processing_jobs", "lease_expires_at")
