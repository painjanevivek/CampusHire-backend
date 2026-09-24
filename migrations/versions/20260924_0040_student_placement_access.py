"""Add institution-specific academic year start month for placement access."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0040"
down_revision: str | None = "20260924_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("institutions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "academic_year_start_month",
                sa.Integer(),
                nullable=False,
                server_default="6",
            )
        )
        batch_op.alter_column("academic_year_start_month", server_default=None)
    with op.batch_alter_table("student_profiles") as batch_op:
        batch_op.add_column(
            sa.Column("prn_verified_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("prn_verified_by_user_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_student_profiles_prn_verified_by_user_id_users",
            "users",
            ["prn_verified_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("student_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_student_profiles_prn_verified_by_user_id_users",
            type_="foreignkey",
        )
        batch_op.drop_column("prn_verified_by_user_id")
        batch_op.drop_column("prn_verified_at")
    with op.batch_alter_table("institutions") as batch_op:
        batch_op.drop_column("academic_year_start_month")
