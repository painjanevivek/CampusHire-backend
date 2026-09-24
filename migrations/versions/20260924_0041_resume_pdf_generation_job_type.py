"""Add a job type for deterministic generated resume PDFs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0041"
down_revision: str | None = "20260924_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "resume_processing_jobs",
        sa.Column(
            "job_type",
            sa.String(length=32),
            server_default="upload_processing",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_resume_processing_jobs_job_type",
        "resume_processing_jobs",
        ["job_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_resume_processing_jobs_job_type", table_name="resume_processing_jobs")
    op.drop_column("resume_processing_jobs", "job_type")
