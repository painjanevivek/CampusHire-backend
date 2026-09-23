"""Tag Copilot messages with their selected intent."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0038"
down_revision: str | None = "20260923_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_messages", sa.Column("intent", sa.String(length=80), nullable=True))
    op.add_column(
        "ai_messages",
        sa.Column(
            "target_role_id",
            sa.Uuid(),
            sa.ForeignKey("placement_roles.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_ai_messages_target_role_id", "ai_messages", ["target_role_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_messages_target_role_id", table_name="ai_messages")
    op.drop_column("ai_messages", "target_role_id")
    op.drop_column("ai_messages", "intent")
