"""Store verified student sign-up details through activation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0029"
down_revision: str | None = "20260913_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "student_registration_requests", sa.Column("first_name", sa.String(100), nullable=True)
    )
    op.add_column(
        "student_registration_requests", sa.Column("surname", sa.String(100), nullable=True)
    )
    op.add_column(
        "student_registration_requests", sa.Column("date_of_birth", sa.Date(), nullable=True)
    )
    op.add_column(
        "student_registration_requests", sa.Column("password_hash", sa.String(512), nullable=True)
    )
    op.add_column("student_profiles", sa.Column("date_of_birth", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("student_profiles", "date_of_birth")
    op.drop_column("student_registration_requests", "password_hash")
    op.drop_column("student_registration_requests", "date_of_birth")
    op.drop_column("student_registration_requests", "surname")
    op.drop_column("student_registration_requests", "first_name")
