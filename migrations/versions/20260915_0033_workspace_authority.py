"""Separate platform authority and add accountable case ownership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0033"
down_revision: str | None = "20260915_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_admin_assignment",
        sa.Column("singleton_key", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("singleton_key = 1", name="ck_platform_admin_singleton_key"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("singleton_key"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "ix_platform_admin_assignment_user_id",
        "platform_admin_assignment",
        ["user_id"],
        unique=True,
    )
    op.create_table(
        "platform_admin_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("previous_user_id", sa.Uuid(), nullable=True),
        sa.Column("new_user_id", sa.Uuid(), nullable=False),
        sa.Column("transferred_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["new_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transferred_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("previous_user_id", "new_user_id", "transferred_by_user_id", "created_at"):
        op.create_index(
            f"ix_platform_admin_transfers_{column}", "platform_admin_transfers", [column]
        )

    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_platform_settings_updated_by_user_id",
        "platform_settings",
        ["updated_by_user_id"],
    )

    op.add_column("applications", sa.Column("assignee_user_id", sa.Uuid(), nullable=True))
    op.add_column("applications", sa.Column("review_due_at", sa.DateTime(timezone=True)))
    op.add_column(
        "applications",
        sa.Column("assignment_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_applications_assignee_user_id",
        "applications",
        "users",
        ["assignee_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_applications_assignee_user_id", "applications", ["assignee_user_id"])
    op.create_index("ix_applications_review_due_at", "applications", ["review_due_at"])

    op.add_column("application_appeals", sa.Column("assignee_user_id", sa.Uuid(), nullable=True))
    op.add_column("application_appeals", sa.Column("due_at", sa.DateTime(timezone=True)))
    op.add_column(
        "application_appeals",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "application_appeals",
        sa.Column("escalation_state", sa.String(length=32), nullable=False, server_default="none"),
    )
    op.add_column(
        "application_appeals",
        sa.Column("disputed_decision_actor_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_application_appeals_assignee_user_id",
        "application_appeals",
        "users",
        ["assignee_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_application_appeals_disputed_actor",
        "application_appeals",
        "users",
        ["disputed_decision_actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in (
        "assignee_user_id",
        "due_at",
        "escalation_state",
        "disputed_decision_actor_user_id",
    ):
        op.create_index(f"ix_application_appeals_{column}", "application_appeals", [column])

    op.create_table(
        "case_assignment_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("case_type", sa.String(length=24), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("from_assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("to_assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["from_assignee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["to_assignee_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "institution_id",
        "case_type",
        "case_id",
        "to_assignee_user_id",
        "actor_user_id",
        "created_at",
    ):
        op.create_index(f"ix_case_assignment_history_{column}", "case_assignment_history", [column])

    op.create_table(
        "privacy_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("subject_reference", sa.String(length=64), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("request_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="submitted"),
        sa.Column("details", sa.String(length=2000), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_summary", sa.String(length=2000), nullable=True),
        sa.Column("cleanup_request_id", sa.Uuid(), nullable=True),
        sa.Column("receipt_reference", sa.String(length=100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cleanup_request_id"], ["data_deletion_requests.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_reference"),
    )
    for column in (
        "user_id",
        "subject_reference",
        "institution_id",
        "request_type",
        "status",
        "owner_user_id",
        "due_at",
    ):
        op.create_index(f"ix_privacy_requests_{column}", "privacy_requests", [column])

    op.create_table(
        "retention_classes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("disposal_action", sa.String(length=32), nullable=False, server_default="delete"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_retention_classes_code", "retention_classes", ["code"], unique=True)
    op.create_index("ix_retention_classes_is_active", "retention_classes", ["is_active"])

    op.create_table(
        "legal_holds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("review_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("release_reason", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["released_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("institution_id", "user_id", "owner_user_id", "review_at"):
        op.create_index(f"ix_legal_holds_{column}", "legal_holds", [column])


def downgrade() -> None:
    for column in ("review_at", "owner_user_id", "user_id", "institution_id"):
        op.drop_index(f"ix_legal_holds_{column}", table_name="legal_holds")
    op.drop_table("legal_holds")
    op.drop_index("ix_retention_classes_is_active", table_name="retention_classes")
    op.drop_index("ix_retention_classes_code", table_name="retention_classes")
    op.drop_table("retention_classes")
    for column in (
        "due_at",
        "owner_user_id",
        "status",
        "request_type",
        "institution_id",
        "subject_reference",
        "user_id",
    ):
        op.drop_index(f"ix_privacy_requests_{column}", table_name="privacy_requests")
    op.drop_table("privacy_requests")
    for column in (
        "created_at",
        "actor_user_id",
        "to_assignee_user_id",
        "case_id",
        "case_type",
        "institution_id",
    ):
        op.drop_index(f"ix_case_assignment_history_{column}", table_name="case_assignment_history")
    op.drop_table("case_assignment_history")
    for column in (
        "disputed_decision_actor_user_id",
        "escalation_state",
        "due_at",
        "assignee_user_id",
    ):
        op.drop_index(f"ix_application_appeals_{column}", table_name="application_appeals")
    op.drop_constraint(
        "fk_application_appeals_disputed_actor", "application_appeals", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_application_appeals_assignee_user_id", "application_appeals", type_="foreignkey"
    )
    for column in (
        "disputed_decision_actor_user_id",
        "escalation_state",
        "revision",
        "due_at",
        "assignee_user_id",
    ):
        op.drop_column("application_appeals", column)
    op.drop_index("ix_applications_review_due_at", table_name="applications")
    op.drop_index("ix_applications_assignee_user_id", table_name="applications")
    op.drop_constraint("fk_applications_assignee_user_id", "applications", type_="foreignkey")
    for column in ("assignment_revision", "review_due_at", "assignee_user_id"):
        op.drop_column("applications", column)
    op.drop_index("ix_platform_settings_updated_by_user_id", table_name="platform_settings")
    op.drop_table("platform_settings")
    for column in ("created_at", "transferred_by_user_id", "new_user_id", "previous_user_id"):
        op.drop_index(
            f"ix_platform_admin_transfers_{column}", table_name="platform_admin_transfers"
        )
    op.drop_table("platform_admin_transfers")
    op.drop_index("ix_platform_admin_assignment_user_id", table_name="platform_admin_assignment")
    op.drop_table("platform_admin_assignment")
