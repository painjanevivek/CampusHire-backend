"""Remember attachment labels and short AI summaries in student conversations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0044"
down_revision: str | None = "20260925_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_messages", sa.Column("attachment_name", sa.String(length=120), nullable=True))
    op.add_column("ai_messages", sa.Column("attachment_context", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_messages", "attachment_context")
    op.drop_column("ai_messages", "attachment_name")
