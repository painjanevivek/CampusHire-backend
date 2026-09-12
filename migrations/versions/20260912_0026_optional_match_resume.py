"""Allow semantic evidence to rely on reviewed profile evidence without a resume."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0026"
down_revision: str | None = "20260912_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("semantic_match_evidence", "resume_version_id", nullable=True)


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM semantic_match_evidence WHERE resume_version_id IS NULL"))
    op.alter_column("semantic_match_evidence", "resume_version_id", nullable=False)
