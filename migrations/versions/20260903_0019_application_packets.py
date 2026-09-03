"""add role-specific application packets

Revision ID: 20260903_0019
Revises: 20260902_0018
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0019"
down_revision: str | None = "20260902_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    op.add_column("student_profiles", sa.Column("city", sa.String(120), nullable=True))
    op.add_column("student_profiles", sa.Column("country_code", sa.String(2), nullable=True))

    op.add_column(
        "resume_versions",
        sa.Column(
            "parent_version_id",
            sa.Uuid(),
            sa.ForeignKey("resume_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "resume_versions",
        sa.Column(
            "purpose_role_id",
            sa.Uuid(),
            sa.ForeignKey("placement_roles.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_resume_versions_parent_version_id", "resume_versions", ["parent_version_id"]
    )
    op.create_index("ix_resume_versions_purpose_role_id", "resume_versions", ["purpose_role_id"])

    op.create_table(
        "role_application_forms",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("compliance_owner", sa.String(160), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("questions", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("role_id", "version", name="uq_role_application_form_version"),
    )
    for column in ("institution_id", "role_id", "status", "created_by_user_id"):
        op.create_index(f"ix_role_application_forms_{column}", "role_application_forms", [column])

    op.add_column(
        "applications",
        sa.Column("profile_snapshot", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.add_column(
        "applications",
        sa.Column(
            "application_form_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "applications",
        sa.Column(
            "disclosure_status", sa.String(32), server_default="not_configured", nullable=False
        ),
    )

    op.create_table(
        "application_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=False),
        sa.Column("form_version_id", sa.Uuid(), nullable=True),
        sa.Column("resume_version_id", sa.Uuid(), nullable=True),
        sa.Column("profile_revision", sa.Integer(), nullable=True),
        sa.Column("current_step", sa.String(32), server_default="resume", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_application_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["form_version_id"], ["role_application_forms.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["resume_version_id"], ["resume_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["submitted_application_id"], ["applications.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "institution_id",
            "student_user_id",
            "role_id",
            name="uq_application_draft_student_role",
        ),
    )
    for column in (
        "institution_id",
        "role_id",
        "student_user_id",
        "form_version_id",
        "resume_version_id",
        "expires_at",
        "last_saved_at",
    ):
        op.create_index(f"ix_application_drafts_{column}", "application_drafts", [column])

    op.create_table(
        "application_disclosure_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("application_draft_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_draft_id"], ["application_drafts.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("application_draft_id"),
    )
    op.create_index(
        "ix_application_disclosure_drafts_application_draft_id",
        "application_disclosure_drafts",
        ["application_draft_id"],
    )
    op.create_index(
        "ix_application_disclosure_drafts_answered_at",
        "application_disclosure_drafts",
        ["answered_at"],
    )

    op.create_table(
        "application_disclosures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("form_version_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["form_version_id"], ["role_application_forms.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("application_id"),
    )
    for column in (
        "institution_id",
        "application_id",
        "form_version_id",
        "retention_until",
        "created_at",
    ):
        op.create_index(f"ix_application_disclosures_{column}", "application_disclosures", [column])


def downgrade() -> None:
    op.drop_table("application_disclosures")
    op.drop_table("application_disclosure_drafts")
    op.drop_table("application_drafts")

    op.drop_column("applications", "disclosure_status")
    op.drop_column("applications", "application_form_snapshot")
    op.drop_column("applications", "profile_snapshot")

    op.drop_table("role_application_forms")

    op.drop_index("ix_resume_versions_purpose_role_id", table_name="resume_versions")
    op.drop_index("ix_resume_versions_parent_version_id", table_name="resume_versions")
    op.drop_column("resume_versions", "purpose_role_id")
    op.drop_column("resume_versions", "parent_version_id")

    op.drop_column("student_profiles", "country_code")
    op.drop_column("student_profiles", "city")
