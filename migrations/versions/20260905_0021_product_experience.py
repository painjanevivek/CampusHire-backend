"""Add supplemental corrections, browsing views, and review revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260905_0021"
down_revision: str | None = "20260905_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
        sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.add_column(
        "applications", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "correction_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), sa.ForeignKey("institutions.id"), nullable=False),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), server_default="open", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        *timestamps(),
    )
    for name in ("institution_id", "application_id", "deadline_at", "status"):
        op.create_index(f"ix_correction_requests_{name}", "correction_requests", [name])
    op.create_table(
        "correction_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("correction_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "resume_version_id",
            sa.Uuid(),
            sa.ForeignKey("resume_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_correction_events_request_id", "correction_events", ["request_id"])
    op.create_table(
        "saved_opportunity_views",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("institution_id", sa.Uuid(), sa.ForeignKey("institutions.id"), nullable=False),
        sa.Column(
            "student_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        *timestamps(),
    )
    for name in ("institution_id", "student_user_id"):
        op.create_index(f"ix_saved_opportunity_views_{name}", "saved_opportunity_views", [name])
    op.add_column(
        "in_app_notifications",
        sa.Column("category", sa.String(24), server_default="updates", nullable=False),
    )
    for name, table in (
        ("related_request_id", "correction_requests"),
        ("related_application_id", "applications"),
    ):
        op.add_column("in_app_notifications", sa.Column(name, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_notification_{name}",
            "in_app_notifications",
            table,
            [name],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for name in ("related_request_id", "related_application_id"):
        op.drop_constraint(f"fk_notification_{name}", "in_app_notifications", type_="foreignkey")
        op.drop_column("in_app_notifications", name)
    op.drop_column("in_app_notifications", "category")
    op.drop_table("saved_opportunity_views")
    op.drop_table("correction_events")
    op.drop_table("correction_requests")
    op.drop_column("applications", "revision")
