"""Enable student Copilot for the active PCCOE signup institution."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0043"
down_revision: str | None = "20260925_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    institutions = sa.table(
        "institutions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String(length=32)),
    )
    flags = sa.table(
        "institution_feature_flags",
        sa.column("institution_id", sa.Uuid()),
        sa.column("ai_generation", sa.Boolean()),
        sa.column("student_copilot", sa.Boolean()),
    )
    institution_id = bind.execute(
        sa.select(institutions.c.id).where(institutions.c.code == "pccoe-pune")
    ).scalar_one_or_none()
    if institution_id is None:
        raise RuntimeError("The PCCOE institution must exist before enabling student Copilot")

    existing = bind.execute(
        sa.select(flags.c.institution_id).where(flags.c.institution_id == institution_id)
    ).scalar_one_or_none()
    if existing is None:
        bind.execute(
            sa.insert(flags).values(
                institution_id=institution_id,
                ai_generation=True,
                student_copilot=True,
            )
        )
    else:
        bind.execute(
            sa.update(flags)
            .where(flags.c.institution_id == institution_id)
            .values(ai_generation=True, student_copilot=True)
        )


def downgrade() -> None:
    # Keep an already enabled capability active for existing student conversations.
    pass
