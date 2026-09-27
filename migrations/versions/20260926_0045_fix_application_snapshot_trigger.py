"""Compare application JSON snapshots as JSONB in the immutability trigger."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260926_0045"
down_revision: str | None = "20260925_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL's json type has no equality operator. The original trigger
    # fails on every UPDATE, including the first packet-finalization update.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_application_snapshot_replacement()
        RETURNS trigger AS $$
        BEGIN
          IF OLD.packet_digest IS NOT NULL AND (
            NEW.role_snapshot::jsonb IS DISTINCT FROM OLD.role_snapshot::jsonb OR
            NEW.resume_snapshot::jsonb IS DISTINCT FROM OLD.resume_snapshot::jsonb OR
            NEW.facts_snapshot::jsonb IS DISTINCT FROM OLD.facts_snapshot::jsonb OR
            NEW.rule_snapshot::jsonb IS DISTINCT FROM OLD.rule_snapshot::jsonb OR
            NEW.eligibility_snapshot::jsonb IS DISTINCT FROM OLD.eligibility_snapshot::jsonb OR
            NEW.decision_snapshot::jsonb IS DISTINCT FROM OLD.decision_snapshot::jsonb OR
            NEW.profile_snapshot::jsonb IS DISTINCT FROM OLD.profile_snapshot::jsonb OR
            NEW.application_form_snapshot::jsonb
              IS DISTINCT FROM OLD.application_form_snapshot::jsonb OR
            NEW.material_terms_snapshot::jsonb
              IS DISTINCT FROM OLD.material_terms_snapshot::jsonb OR
            NEW.acknowledgment_snapshot::jsonb
              IS DISTINCT FROM OLD.acknowledgment_snapshot::jsonb OR
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


def downgrade() -> None:
    # Restore the original definition when rolling back this migration.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_application_snapshot_replacement()
        RETURNS trigger AS $$
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
