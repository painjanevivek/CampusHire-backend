"""Add normalized student evidence and institution onboarding."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0025"
down_revision: str | None = "20260912_0024"
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
    op.add_column("student_profiles", sa.Column("graduation_year", sa.Integer(), nullable=True))
    op.add_column(
        "student_profiles", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True))
    )
    op.create_table(
        "student_education",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("qualification_level", sa.String(32), nullable=False),
        sa.Column("degree", sa.String(120), nullable=False),
        sa.Column("branch", sa.String(120), nullable=False),
        sa.Column("institution", sa.String(200), nullable=False),
        sa.Column("start_year", sa.Integer(), nullable=True),
        sa.Column("graduation_year", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_scale", sa.String(24), nullable=False),
        sa.Column("active_backlogs", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["profile_id"], ["student_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_student_education_profile_id", "student_education", ["profile_id"])
    op.create_table(
        "student_experiences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("organization", sa.String(200), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("responsibilities", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["profile_id"], ["student_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_student_experiences_profile_id", "student_experiences", ["profile_id"])
    op.create_table(
        "student_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("technologies", sa.JSON(), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("project_url", sa.String(500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["profile_id"], ["student_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_student_projects_profile_id", "student_projects", ["profile_id"])
    op.create_table(
        "student_certifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("issuer", sa.String(200), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("credential_url", sa.String(500), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["profile_id"], ["student_profiles.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_student_certifications_profile_id", "student_certifications", ["profile_id"]
    )
    op.create_table(
        "student_career_preferences",
        sa.Column("profile_id", sa.Uuid(), primary_key=True),
        sa.Column("target_roles", sa.JSON(), nullable=False),
        sa.Column("industries", sa.JSON(), nullable=False),
        sa.Column("locations", sa.JSON(), nullable=False),
        sa.Column("job_types", sa.JSON(), nullable=False),
        sa.Column("work_modes", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["profile_id"], ["student_profiles.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "student_placement_participation",
        sa.Column("profile_id", sa.Uuid(), primary_key=True),
        sa.Column("placement_cycle", sa.String(120), nullable=False),
        sa.Column("communication_channels", sa.JSON(), nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("privacy_accepted", sa.Boolean(), nullable=False),
        sa.Column("privacy_accepted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["profile_id"], ["student_profiles.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "institution_onboarding",
        sa.Column("institution_id", sa.Uuid(), primary_key=True),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("completed_steps", sa.JSON(), nullable=False),
        sa.Column("step_data", sa.JSON(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
    )
    op.create_table(
        "institution_campuses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("institution_id", "name", name="uq_institution_campus_name"),
    )
    op.create_index(
        "ix_institution_campuses_institution_id", "institution_campuses", ["institution_id"]
    )
    op.create_table(
        "institution_programs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campus_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("branches", sa.JSON(), nullable=False),
        sa.Column("graduating_batches", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["campus_id"], ["institution_campuses.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_institution_programs_campus_id", "institution_programs", ["campus_id"])
    op.create_table(
        "institution_feature_flags",
        sa.Column("institution_id", sa.Uuid(), primary_key=True),
        sa.Column("ai_generation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ai_resume_studio", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("student_copilot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tnp_copilot", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("institution_feature_flags")
    op.drop_table("institution_programs")
    op.drop_table("institution_campuses")
    op.drop_table("institution_onboarding")
    op.drop_table("student_placement_participation")
    op.drop_table("student_career_preferences")
    op.drop_table("student_certifications")
    op.drop_table("student_projects")
    op.drop_table("student_experiences")
    op.drop_table("student_education")
    op.drop_column("student_profiles", "onboarding_completed_at")
    op.drop_column("student_profiles", "graduation_year")
