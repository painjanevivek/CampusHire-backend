"""Add bounded agent runs, reviewable artifacts, sources, and consent."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0028"
down_revision: str | None = "20260912_0027"
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
    op.add_column(
        "institution_feature_flags",
        sa.Column("agent_runs", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "institution_feature_flags",
        sa.Column("live_sources", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "institution_feature_flags",
        sa.Column("practice_aggregates", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "placement_drives", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("audience", sa.String(24), nullable=False),
        sa.Column("workflow", sa.String(64), nullable=False),
        sa.Column("target_kind", sa.String(24), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("checkpoint_data", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=True),
        sa.Column("model_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correction_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_time_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_cost_microunits", sa.Integer(), nullable=False, server_default="30000"),
        sa.Column("actual_cost_microunits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("required_action", sa.JSON(), nullable=True),
        sa.Column("safe_error", sa.Text(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "institution_id", "user_id", "workflow", "idempotency_key",
            name="uq_agent_runs_idempotency",
        ),
    )
    for column in (
        "institution_id", "user_id", "audience", "workflow", "target_id", "status",
        "source_fingerprint", "lease_owner", "expires_at",
    ):
        op.create_index(f"ix_agent_runs_{column}", "agent_runs", [column])

    op.create_table(
        "agent_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("summary", sa.String(240), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_events_sequence"),
    )
    op.create_index("ix_agent_events_run_id", "agent_events", ["run_id"])
    op.create_index("ix_agent_events_event_type", "agent_events", ["event_type"])

    op.create_table(
        "preparation_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("evidence_references", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="CASCADE"),
    )
    for column in (
        "run_id",
        "institution_id",
        "student_id",
        "role_id",
        "status",
        "source_fingerprint",
    ):
        op.create_index(f"ix_preparation_plans_{column}", "preparation_plans", [column])

    op.create_table(
        "drive_preparation_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("drive_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("source_drive_revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("evidence_references", sa.JSON(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["drive_id"], ["placement_drives.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
    )
    for column in ("run_id", "institution_id", "drive_id", "status", "source_fingerprint"):
        op.create_index(
            f"ix_drive_preparation_artifacts_{column}", "drive_preparation_artifacts", [column]
        )

    op.create_table(
        "source_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("canonical_url", sa.String(1000), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("review_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("access_scope", sa.String(40), nullable=False, server_default="institution"),
        sa.Column("permitted_use", sa.String(240), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("etag", sa.String(300), nullable=True),
        sa.Column("last_modified", sa.String(300), nullable=True),
        sa.Column("safe_error", sa.String(300), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "institution_id", "canonical_url", "version", name="uq_source_versions_version"
        ),
    )
    for column in ("institution_id", "source_type", "review_status", "content_digest", "active"):
        op.create_index(f"ix_source_versions_{column}", "source_versions", [column])

    op.create_table(
        "generation_usage",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_microunits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "attempt", name="uq_generation_usage_attempt"),
    )
    op.create_index("ix_generation_usage_run_id", "generation_usage", ["run_id"])
    op.create_index("ix_generation_usage_institution_id", "generation_usage", ["institution_id"])

    op.create_table(
        "practice_consents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(80), nullable=False, server_default="practice_aggregates"),
        sa.Column("consent_version", sa.String(40), nullable=False),
        sa.Column("opted_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "institution_id", "student_id", "purpose", name="uq_practice_consents_purpose"
        ),
    )
    op.create_index("ix_practice_consents_institution_id", "practice_consents", ["institution_id"])
    op.create_index("ix_practice_consents_student_id", "practice_consents", ["student_id"])


def downgrade() -> None:
    op.drop_table("practice_consents")
    op.drop_table("generation_usage")
    op.drop_table("source_versions")
    op.drop_table("drive_preparation_artifacts")
    op.drop_table("preparation_plans")
    op.drop_table("agent_events")
    op.drop_table("agent_runs")
    op.drop_column("placement_drives", "revision")
    op.drop_column("institution_feature_flags", "practice_aggregates")
    op.drop_column("institution_feature_flags", "live_sources")
    op.drop_column("institution_feature_flags", "agent_runs")
