"""Add append-only placement outcomes and versioned metric definitions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0035"
down_revision: str | None = "20260923_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OUTCOME_TYPES = (
    "'selection', 'offer_issued', 'offer_accepted', 'offer_declined', "
    "'offer_rescinded', 'joining_deferred', 'joining', 'no_show', "
    "'placement_confirmed', 'internship', 'ppo', 'higher_studies', "
    "'approved_off_campus'"
)


def upgrade() -> None:
    op.create_table(
        "outcome_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("outcome_state", sa.String(length=16), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_reference", sa.String(length=500)),
        sa.Column("evidence_reference", sa.String(length=500)),
        sa.Column("verified_by_user_id", sa.Uuid()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("compensation_amount", sa.Numeric(14, 2)),
        sa.Column("compensation_currency", sa.String(length=3)),
        sa.Column("compensation_period", sa.String(length=16)),
        sa.Column("stipend_amount", sa.Numeric(14, 2)),
        sa.Column("joining_date", sa.Date()),
        sa.Column("joining_location", sa.String(length=200)),
        sa.Column("next_update_owner", sa.String(length=160)),
        sa.Column("next_update_due_at", sa.DateTime(timezone=True)),
        sa.Column("supersedes_event_id", sa.Uuid()),
        sa.Column("correction_reason", sa.String(length=1000)),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome_state IN ('provisional', 'verified')",
            name="ck_outcome_event_state",
        ),
        sa.CheckConstraint(
            f"event_type IN ({OUTCOME_TYPES})",
            name="ck_outcome_event_type",
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supersedes_event_id"], ["outcome_events.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supersedes_event_id", name="uq_outcome_event_supersedes_once"),
    )
    for column in (
        "institution_id",
        "application_id",
        "student_user_id",
        "event_type",
        "outcome_state",
        "event_at",
        "verified_by_user_id",
        "next_update_due_at",
        "created_by_user_id",
        "created_at",
    ):
        op.create_index(f"ix_outcome_events_{column}", "outcome_events", [column])

    op.create_table(
        "metric_definition_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("numerator", sa.JSON(), nullable=False),
        sa.Column("denominator", sa.JSON(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("evidence_requirements", sa.JSON(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid()),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_metric_definition_code_version"),
    )
    for column in ("code", "status", "effective_at", "created_by_user_id"):
        op.create_index(
            f"ix_metric_definition_versions_{column}",
            "metric_definition_versions",
            [column],
        )


def downgrade() -> None:
    op.drop_table("metric_definition_versions")
    op.drop_table("outcome_events")
