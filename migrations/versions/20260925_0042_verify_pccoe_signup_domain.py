"""Link the PCCOE signup catalog entry to its institutional email domain."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_0042"
down_revision: str | None = "20260924_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    institutions = sa.table(
        "institutions",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String(length=32)),
    )
    domains = sa.table(
        "institution_domains",
        sa.column("id", sa.Uuid()),
        sa.column("institution_id", sa.Uuid()),
        sa.column("domain", sa.String(length=255)),
        sa.column("verification_status", sa.String(length=32)),
        sa.column("verified_at", sa.DateTime(timezone=True)),
    )
    institution_id = bind.execute(
        sa.select(institutions.c.id).where(institutions.c.code == "pccoe-pune")
    ).scalar_one_or_none()
    if institution_id is None:
        raise RuntimeError("The PCCOE signup institution must exist before linking its domain")

    existing = bind.execute(
        sa.select(domains.c.id, domains.c.institution_id, domains.c.verification_status).where(
            domains.c.domain == "pccoepune.org"
        )
    ).one_or_none()
    if existing is None:
        bind.execute(
            sa.insert(domains).values(
                id=uuid4(),
                institution_id=institution_id,
                domain="pccoepune.org",
                verification_status="verified",
                verified_at=sa.func.now(),
            )
        )
    elif existing.institution_id != institution_id:
        raise RuntimeError("The PCCOE domain is already assigned to another institution")
    elif existing.verification_status != "verified":
        bind.execute(
            sa.update(domains)
            .where(domains.c.id == existing.id)
            .values(verification_status="verified", verified_at=sa.func.now())
        )


def downgrade() -> None:
    # Keep the verified domain: existing student accounts may rely on this link.
    pass
