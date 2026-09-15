"""Add versioned material terms and canonical application packet evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0032"
down_revision: str | None = "20260914_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "material_terms_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["role_id"], ["placement_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "version", name="uq_material_terms_role_version"),
    )
    op.create_index(
        "ix_material_terms_versions_institution_id",
        "material_terms_versions",
        ["institution_id"],
    )
    op.create_index("ix_material_terms_versions_role_id", "material_terms_versions", ["role_id"])
    op.create_index("ix_material_terms_versions_status", "material_terms_versions", ["status"])
    op.create_index(
        "ix_material_terms_versions_content_digest",
        "material_terms_versions",
        ["content_digest"],
    )
    op.create_index(
        "ix_material_terms_versions_created_by_user_id",
        "material_terms_versions",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_material_terms_versions_approved_by_user_id",
        "material_terms_versions",
        ["approved_by_user_id"],
    )

    op.add_column("application_drafts", sa.Column("material_terms_version_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_application_drafts_material_terms_version_id",
        "application_drafts",
        "material_terms_versions",
        ["material_terms_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_application_drafts_material_terms_version_id",
        "application_drafts",
        ["material_terms_version_id"],
    )

    op.add_column(
        "applications",
        sa.Column("material_terms_snapshot", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "applications",
        sa.Column("acknowledgment_snapshot", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column("applications", sa.Column("packet_digest", sa.String(length=64)))
    op.add_column(
        "applications",
        sa.Column(
            "evidence_provenance",
            sa.String(length=32),
            nullable=False,
            server_default="legacy_import",
        ),
    )
    op.execute(
        """
        UPDATE applications
        SET packet_digest = md5(CAST(id AS text) || chr(58) || 'legacy-import')
            || md5(chr(58) || 'legacy-import' || chr(58) || CAST(id AS text))
        WHERE packet_digest IS NULL
        """
    )
    op.create_index("ix_applications_packet_digest", "applications", ["packet_digest"])

    op.create_table(
        "application_acknowledgments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("student_user_id", sa.Uuid(), nullable=False),
        sa.Column("material_terms_version_id", sa.Uuid(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("confirmation", sa.String(length=120), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["institution_id"], ["institutions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["material_terms_version_id"], ["material_terms_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id"),
    )
    op.create_index(
        "ix_application_acknowledgments_institution_id",
        "application_acknowledgments",
        ["institution_id"],
    )
    op.create_index(
        "ix_application_acknowledgments_application_id",
        "application_acknowledgments",
        ["application_id"],
        unique=True,
    )
    op.create_index(
        "ix_application_acknowledgments_student_user_id",
        "application_acknowledgments",
        ["student_user_id"],
    )
    op.create_index(
        "ix_application_acknowledgments_material_terms_version_id",
        "application_acknowledgments",
        ["material_terms_version_id"],
    )
    op.create_index(
        "ix_application_acknowledgments_acknowledged_at",
        "application_acknowledgments",
        ["acknowledged_at"],
    )

    op.execute(
        """
        CREATE FUNCTION prevent_application_snapshot_replacement() RETURNS trigger AS $$
        BEGIN
          IF OLD.packet_digest IS NOT NULL AND (
            NEW.role_snapshot IS DISTINCT FROM OLD.role_snapshot OR
            NEW.resume_snapshot IS DISTINCT FROM OLD.resume_snapshot OR
            NEW.facts_snapshot IS DISTINCT FROM OLD.facts_snapshot OR
            NEW.rule_snapshot IS DISTINCT FROM OLD.rule_snapshot OR
            NEW.eligibility_snapshot IS DISTINCT FROM OLD.eligibility_snapshot OR
            NEW.decision_snapshot IS DISTINCT FROM OLD.decision_snapshot OR
            NEW.profile_snapshot IS DISTINCT FROM OLD.profile_snapshot OR
            NEW.application_form_snapshot IS DISTINCT FROM OLD.application_form_snapshot OR
            NEW.material_terms_snapshot IS DISTINCT FROM OLD.material_terms_snapshot OR
            NEW.acknowledgment_snapshot IS DISTINCT FROM OLD.acknowledgment_snapshot OR
            NEW.packet_digest IS DISTINCT FROM OLD.packet_digest OR
            NEW.evidence_provenance IS DISTINCT FROM OLD.evidence_provenance
          ) THEN
            RAISE EXCEPTION 'submitted_application_snapshot_immutable';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_applications_immutable_snapshot
        BEFORE UPDATE ON applications
        FOR EACH ROW EXECUTE FUNCTION prevent_application_snapshot_replacement();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_applications_immutable_snapshot ON applications")
    op.execute("DROP FUNCTION IF EXISTS prevent_application_snapshot_replacement")
    op.drop_index(
        "ix_application_acknowledgments_acknowledged_at",
        table_name="application_acknowledgments",
    )
    op.drop_index(
        "ix_application_acknowledgments_material_terms_version_id",
        table_name="application_acknowledgments",
    )
    op.drop_index(
        "ix_application_acknowledgments_student_user_id",
        table_name="application_acknowledgments",
    )
    op.drop_index(
        "ix_application_acknowledgments_application_id",
        table_name="application_acknowledgments",
    )
    op.drop_index(
        "ix_application_acknowledgments_institution_id",
        table_name="application_acknowledgments",
    )
    op.drop_table("application_acknowledgments")
    op.drop_index("ix_applications_packet_digest", table_name="applications")
    op.drop_column("applications", "evidence_provenance")
    op.drop_column("applications", "packet_digest")
    op.drop_column("applications", "acknowledgment_snapshot")
    op.drop_column("applications", "material_terms_snapshot")
    op.drop_index(
        "ix_application_drafts_material_terms_version_id", table_name="application_drafts"
    )
    op.drop_constraint(
        "fk_application_drafts_material_terms_version_id",
        "application_drafts",
        type_="foreignkey",
    )
    op.drop_column("application_drafts", "material_terms_version_id")
    op.drop_index(
        "ix_material_terms_versions_approved_by_user_id", table_name="material_terms_versions"
    )
    op.drop_index(
        "ix_material_terms_versions_created_by_user_id", table_name="material_terms_versions"
    )
    op.drop_index("ix_material_terms_versions_content_digest", table_name="material_terms_versions")
    op.drop_index("ix_material_terms_versions_status", table_name="material_terms_versions")
    op.drop_index("ix_material_terms_versions_role_id", table_name="material_terms_versions")
    op.drop_index(
        "ix_material_terms_versions_institution_id", table_name="material_terms_versions"
    )
    op.drop_table("material_terms_versions")
