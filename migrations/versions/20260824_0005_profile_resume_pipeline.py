"""Add profile concurrency and the reviewed resume pipeline.

Revision ID: 20260824_0005
Revises: 20260823_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0005"
down_revision: str | None = "20260823_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("student_profiles", sa.Column("institution_id", sa.Uuid(), nullable=True))
    op.add_column(
        "student_profiles",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_foreign_key(
        "fk_student_profiles_institution_id",
        "student_profiles",
        "institutions",
        ["institution_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_student_profiles_institution_id", "student_profiles", ["institution_id"]
    )

    op.create_table(
        "resumes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("latest_version_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["institution_id"], ["institutions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_resumes_user_id", "resumes", ["user_id"])
    op.create_index("ix_resumes_institution_id", "resumes", ["institution_id"])

    op.add_column("resume_versions", sa.Column("resume_id", sa.Uuid(), nullable=True))
    op.add_column("resume_versions", sa.Column("institution_id", sa.Uuid(), nullable=True))
    op.add_column("resume_versions", sa.Column("version_number", sa.Integer(), nullable=True))
    op.add_column(
        "resume_versions",
        sa.Column("source", sa.String(24), server_default="upload", nullable=False),
    )
    op.add_column(
        "resume_versions",
        sa.Column("content_type", sa.String(80), server_default="application/pdf", nullable=False),
    )
    op.add_column(
        "resume_versions", sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "resume_versions",
        sa.Column("scan_status", sa.String(24), server_default="quarantined", nullable=False),
    )
    op.add_column("resume_versions", sa.Column("scan_engine", sa.String(80), nullable=True))
    op.add_column(
        "resume_versions", sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "resume_versions",
        sa.Column("retention_class", sa.String(40), server_default="active_resume", nullable=False),
    )
    op.add_column(
        "resume_versions",
        sa.Column(
            "extracted_data",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.add_column(
        "resume_versions",
        sa.Column("review_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_resume_versions_resume_id",
        "resume_versions",
        "resumes",
        ["resume_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_resume_versions_institution_id",
        "resume_versions",
        "institutions",
        ["institution_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_resume_versions_resume_id", "resume_versions", ["resume_id"])
    op.create_index(
        "ix_resume_versions_institution_id", "resume_versions", ["institution_id"]
    )
    op.create_index("ix_resume_versions_scan_status", "resume_versions", ["scan_status"])
    op.create_unique_constraint(
        "uq_resume_version_number", "resume_versions", ["resume_id", "version_number"]
    )

    op.create_table(
        "resume_processing_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resume_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), server_default="queued", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["resume_version_id"], ["resume_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resume_version_id"),
    )
    op.create_index(
        "ix_resume_processing_jobs_resume_version_id",
        "resume_processing_jobs",
        ["resume_version_id"],
    )
    op.create_index("ix_resume_processing_jobs_status", "resume_processing_jobs", ["status"])
    op.create_index(
        "ix_resume_processing_jobs_available_at", "resume_processing_jobs", ["available_at"]
    )

    op.create_table(
        "resume_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("resume_version_id", sa.Uuid(), nullable=False),
        sa.Column("field_path", sa.String(160), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("proposed_text", sa.Text(), nullable=False),
        sa.Column("rationale", sa.String(500), nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("decided_text", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["resume_version_id"], ["resume_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resume_version_id", "field_path", name="uq_resume_suggestion_field"
        ),
    )
    op.create_index(
        "ix_resume_suggestions_resume_version_id",
        "resume_suggestions",
        ["resume_version_id"],
    )
    op.create_index("ix_resume_suggestions_status", "resume_suggestions", ["status"])


def downgrade() -> None:
    op.drop_table("resume_suggestions")
    op.drop_table("resume_processing_jobs")
    op.drop_constraint("uq_resume_version_number", "resume_versions", type_="unique")
    op.drop_index("ix_resume_versions_scan_status", table_name="resume_versions")
    op.drop_index("ix_resume_versions_institution_id", table_name="resume_versions")
    op.drop_index("ix_resume_versions_resume_id", table_name="resume_versions")
    op.drop_constraint("fk_resume_versions_institution_id", "resume_versions", type_="foreignkey")
    op.drop_constraint("fk_resume_versions_resume_id", "resume_versions", type_="foreignkey")
    for column in (
        "review_completed_at",
        "extracted_data",
        "retention_class",
        "scanned_at",
        "scan_engine",
        "scan_status",
        "size_bytes",
        "content_type",
        "source",
        "version_number",
        "institution_id",
        "resume_id",
    ):
        op.drop_column("resume_versions", column)
    op.drop_table("resumes")
    op.drop_index("ix_student_profiles_institution_id", table_name="student_profiles")
    op.drop_constraint("fk_student_profiles_institution_id", "student_profiles", type_="foreignkey")
    op.drop_column("student_profiles", "revision")
    op.drop_column("student_profiles", "institution_id")
