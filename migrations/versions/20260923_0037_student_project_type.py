"""Store a project type for student onboarding projects."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0037"
down_revision: str | None = "20260923_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "student_projects",
        sa.Column("project_type", sa.String(length=24), server_default="other", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("student_projects", "project_type")
