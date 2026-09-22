"""Persist agent release identity and fail-safe evaluation provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0034"
down_revision: str | None = "20260915_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_provenance_columns(table_name: str) -> None:
    op.add_column(
        table_name,
        sa.Column(
            "provider_name", sa.String(length=80), nullable=False,
            server_default="unrecorded-legacy",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "model_version", sa.String(length=120), nullable=False,
            server_default="unrecorded-legacy",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "workflow_version", sa.String(length=80), nullable=False,
            server_default="campus-agent-v1",
        ),
    )
    op.add_column(
        table_name,
        sa.Column(
            "source_projection_version", sa.String(length=80), nullable=False,
            server_default="agent-source-projection-v1",
        ),
    )
    op.add_column(table_name, sa.Column("evaluation_run_id", sa.String(length=120)))


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column(
            "workflow_version", sa.String(length=80), nullable=False,
            server_default="campus-agent-v1",
        ),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "source_projection_version", sa.String(length=80), nullable=False,
            server_default="agent-source-projection-v1",
        ),
    )
    op.add_column("agent_runs", sa.Column("evaluation_run_id", sa.String(length=120)))
    op.add_column(
        "agent_runs",
        sa.Column("provider_name", sa.String(length=80), nullable=False, server_default="gemini"),
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "model_version", sa.String(length=120), nullable=False,
            server_default="unrecorded-legacy",
        ),
    )
    _add_provenance_columns("preparation_plans")
    _add_provenance_columns("drive_preparation_artifacts")


def downgrade() -> None:
    for table_name in ("drive_preparation_artifacts", "preparation_plans"):
        for column in (
            "evaluation_run_id",
            "source_projection_version",
            "workflow_version",
            "model_version",
            "provider_name",
        ):
            op.drop_column(table_name, column)
    for column in (
        "model_version",
        "provider_name",
        "evaluation_run_id",
        "source_projection_version",
        "workflow_version",
    ):
        op.drop_column("agent_runs", column)
