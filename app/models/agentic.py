from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "user_id", "workflow", "idempotency_key",
            name="uq_agent_runs_idempotency",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    audience: Mapped[str] = mapped_column(String(24), index=True)
    workflow: Mapped[str] = mapped_column(String(64), index=True)
    workflow_version: Mapped[str] = mapped_column(String(80), default="campus-agent-v1")
    source_projection_version: Mapped[str] = mapped_column(
        String(80), default="agent-source-projection-v1"
    )
    evaluation_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_name: Mapped[str] = mapped_column(String(80), default="gemini")
    model_version: Mapped[str] = mapped_column(String(120), default="unconfigured")
    target_kind: Mapped[str] = mapped_column(String(24))
    target_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checkpoint_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    correction_attempts: Mapped[int] = mapped_column(Integer, default=0)
    active_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    reserved_cost_microunits: Mapped[int] = mapped_column(Integer, default=30_000)
    actual_cost_microunits: Mapped[int] = mapped_column(Integer, default=0)
    required_action: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    safe_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AgentEvent(Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence", name="uq_agent_events_sequence"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    summary: Mapped[str] = mapped_column(String(240))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PreparationPlan(Base, TimestampMixin):
    __tablename__ = "preparation_plans"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_roles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    provider_name: Mapped[str] = mapped_column(String(80), default="unrecorded-legacy")
    model_version: Mapped[str] = mapped_column(String(120), default="unrecorded-legacy")
    workflow_version: Mapped[str] = mapped_column(String(80), default="campus-agent-v1")
    source_projection_version: Mapped[str] = mapped_column(
        String(80), default="agent-source-projection-v1"
    )
    evaluation_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DrivePreparationArtifact(Base, TimestampMixin):
    __tablename__ = "drive_preparation_artifacts"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    drive_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_drives.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source_drive_revision: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_references: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    provider_name: Mapped[str] = mapped_column(String(80), default="unrecorded-legacy")
    model_version: Mapped[str] = mapped_column(String(120), default="unrecorded-legacy")
    workflow_version: Mapped[str] = mapped_column(String(80), default="campus-agent-v1")
    source_projection_version: Mapped[str] = mapped_column(
        String(80), default="agent-source-projection-v1"
    )
    evaluation_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceVersion(Base, TimestampMixin):
    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "canonical_url", "version", name="uq_source_versions_version"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    canonical_url: Mapped[str] = mapped_column(String(1_000))
    title: Mapped[str] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    access_scope: Mapped[str] = mapped_column(String(40), default="institution")
    permitted_use: Mapped[str] = mapped_column(String(240))
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_digest: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(300), nullable=True)
    safe_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class GenerationUsage(Base):
    __tablename__ = "generation_usage"
    __table_args__ = (UniqueConstraint("run_id", "attempt", name="uq_generation_usage_attempt"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_microunits: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PracticeConsent(Base, TimestampMixin):
    __tablename__ = "practice_consents"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "student_id", "purpose", name="uq_practice_consents_purpose"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(80), default="practice_aggregates")
    consent_version: Mapped[str] = mapped_column(String(40))
    opted_in: Mapped[bool] = mapped_column(Boolean, default=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
