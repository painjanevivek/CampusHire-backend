"""Add the five colleges offered in public student signup."""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0039"
down_revision: str | None = "20260923_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLLEGES = (
    (
        "pccoe-pune",
        "Pimpri Chinchwad College of Engineering (PCCOE), Pune.",
        "b8ec4465-2c42-5b68-941e-dcad75876b22",
    ),
    (
        "pccoer-pune",
        "Pimpri Chinchwad College of Engineering & Research (PCCOE&R), Pune.",
        "bc784fc9-9bad-54f6-b0c7-c65e89bd2a26",
    ),
    (
        "nmiet-pune",
        "Nutan Maharashtra Institute of Engineering & Technology (NMIET), Pune.",
        "cff9fa76-f043-5108-bd18-02002ee7366b",
    ),
    (
        "ncer-pune",
        "Nutan College of Engineering & Research (NCER), Pune.",
        "88555391-9101-538a-b516-75c50ea40d73",
    ),
    (
        "pcu-pune",
        "Pimpri Chinchwad University (PCU), Pune.",
        "b55b92a4-dc50-5d7d-b872-ce37708db52a",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    institutions = sa.table(
        "institutions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String(length=32)),
        sa.column("name", sa.String(length=200)),
        sa.column("is_active", sa.Boolean()),
        sa.column("roadmaps_enabled", sa.Boolean()),
        sa.column("timezone", sa.String(length=64)),
    )
    for code, name, raw_id in _COLLEGES:
        institution_id = UUID(raw_id)
        existing_id = bind.execute(
            sa.select(institutions.c.id).where(institutions.c.code == code)
        ).scalar_one_or_none()
        if existing_id is None:
            bind.execute(
                sa.insert(institutions).values(
                    id=institution_id,
                    code=code,
                    name=name,
                    is_active=True,
                    roadmaps_enabled=True,
                    timezone="Asia/Kolkata",
                )
            )
        else:
            bind.execute(
                sa.update(institutions)
                .where(institutions.c.id == existing_id)
                .values(name=name, is_active=True)
            )


def downgrade() -> None:
    # Keep the provisioned tenant rows: student and recruitment data may now reference them.
    pass
