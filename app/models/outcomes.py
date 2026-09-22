from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OutcomeEvent(Base):
    """Append-only evidence about what happened after an application decision."""

    __tablename__ = "outcome_events"
    __table_args__ = (
        UniqueConstraint("supersedes_event_id", name="uq_outcome_event_supersedes_once"),
        CheckConstraint(
            "outcome_state IN ('provisional', 'verified')",
            name="ck_outcome_event_state",
        ),
        CheckConstraint(
            "event_type IN ('selection', 'offer_issued', 'offer_accepted', "
            "'offer_declined', 'offer_rescinded', 'joining_deferred', 'joining', "
            "'no_show', 'placement_confirmed', 'internship', 'ppo', "
            "'higher_studies', 'approved_off_campus')",
            name="ck_outcome_event_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT"), index=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    outcome_state: Mapped[str] = mapped_column(String(16), index=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_type: Mapped[str] = mapped_column(String(48))
    source_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    verified_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    compensation_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    compensation_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    compensation_period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stipend_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    joining_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    joining_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    next_update_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    next_update_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    supersedes_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outcome_events.id", ondelete="RESTRICT"), nullable=True
    )
    correction_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@event.listens_for(OutcomeEvent, "before_update")
@event.listens_for(OutcomeEvent, "before_delete")
def _protect_outcome_event(*_: object) -> None:
    raise ValueError("outcome_event_append_only")


class MetricDefinitionVersion(Base, TimestampMixin):
    """Versioned, reviewable definition used to interpret placement metrics."""

    __tablename__ = "metric_definition_versions"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_metric_definition_code_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    numerator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    denominator: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    exclusions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
