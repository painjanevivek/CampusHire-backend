"""Add institution-scoped recruitment operations and application snapshots.

Revision ID: 20260824_0006
Revises: 20260824_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0006"
down_revision: str | None = "20260824_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(24), server_default="active", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("institution_id", "name", name="uq_company_institution_name"),
    )
    op.create_index("ix_companies_institution_id", "companies", ["institution_id"])
    op.create_index("ix_companies_status", "companies", ["status"])

    op.create_table(
        "placement_drives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(160), nullable=False),
        sa.Column("work_mode", sa.String(32), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("opens_at < deadline_at", name="ck_drive_application_window"),
    )
    for column in ("institution_id", "company_id", "opens_at", "deadline_at", "status"):
        op.create_index(f"ix_placement_drives_{column}", "placement_drives", [column])

    op.create_table(
        "placement_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("drive_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("employment_type", sa.String(40), nullable=False),
        sa.Column("location", sa.String(160), nullable=False),
        sa.Column("work_mode", sa.String(32), nullable=False),
        sa.Column("salary_display", sa.String(120), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["drive_id"], ["placement_drives.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("institution_id", "drive_id", "status"):
        op.create_index(f"ix_placement_roles_{column}", "placement_roles", [column])

    op.create_table(
        "eligibility_rule_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "version", name="uq_eligibility_rule_role_version"),
    )
    for column in ("institution_id", "role_id", "status", "created_by_user_id"):
        op.create_index(f"ix_eligibility_rule_sets_{column}", "eligibility_rule_sets", [column])

    op.create_table(
        "eligibility_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=False),
        sa.Column("rule_set_id", sa.Uuid(), nullable=False),
        sa.Column("facts_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["eligibility_rule_sets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "institution_id",
        "role_id",
        "student_user_id",
        "rule_set_id",
        "fingerprint",
        "created_at",
    ):
        op.create_index(f"ix_eligibility_evaluations_{column}", "eligibility_evaluations", [column])

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=False),
        sa.Column("resume_version_id", sa.Uuid(), nullable=False),
        sa.Column("eligibility_evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), server_default="submitted", nullable=False),
        sa.Column("role_snapshot", sa.JSON(), nullable=False),
        sa.Column("resume_snapshot", sa.JSON(), nullable=False),
        sa.Column("facts_snapshot", sa.JSON(), nullable=False),
        sa.Column("rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("eligibility_snapshot", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["eligibility_evaluation_id"], ["eligibility_evaluations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["resume_version_id"], ["resume_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_user_id", "role_id", name="uq_application_student_role"),
        sa.UniqueConstraint(
            "institution_id",
            "student_user_id",
            "idempotency_key",
            name="uq_application_idempotency",
        ),
    )
    for column in (
        "institution_id",
        "role_id",
        "student_user_id",
        "resume_version_id",
        "eligibility_evaluation_id",
        "status",
    ):
        op.create_index(f"ix_applications_{column}", "applications", [column])

    op.create_table(
        "application_status_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("application_id", "to_status", "actor_user_id", "created_at"):
        op.create_index(
            f"ix_application_status_events_{column}", "application_status_events", [column]
        )

    op.create_table(
        "application_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("target_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("policy_reference", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("application_id", "actor_user_id", "created_at"):
        op.create_index(f"ix_application_overrides_{column}", "application_overrides", [column])

    op.create_table(
        "saved_opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("student_user_id", "role_id", name="uq_saved_opportunity_student_role"),
    )
    for column in ("institution_id", "student_user_id", "role_id", "created_at"):
        op.create_index(f"ix_saved_opportunities_{column}", "saved_opportunities", [column])


def downgrade() -> None:
    for table in (
        "saved_opportunities",
        "application_overrides",
        "application_status_events",
        "applications",
        "eligibility_evaluations",
        "eligibility_rule_sets",
        "placement_roles",
        "placement_drives",
        "companies",
    ):
        op.drop_table(table)
