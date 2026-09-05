"""Supplemental application evidence and student-owned browsing preferences."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CorrectionRequest(Base, TimestampMixin):
    __tablename__ = "correction_requests"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(ForeignKey("institutions.id"), index=True)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    instructions: Mapped[str] = mapped_column(Text)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class CorrectionEvent(Base):
    __tablename__ = "correction_events"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("correction_requests.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    action: Mapped[str] = mapped_column(String(24))
    body: Mapped[str] = mapped_column(Text)
    resume_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SavedOpportunityView(Base, TimestampMixin):
    __tablename__ = "saved_opportunity_views"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(ForeignKey("institutions.id"), index=True)
    student_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    filters: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class ReviewedPreparationMapping(Base):
    """Explicit institution-reviewed mapping; never inferred from curriculum text."""

    __tablename__ = "reviewed_preparation_mappings"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(ForeignKey("institutions.id"), index=True)
    template_id: Mapped[UUID] = mapped_column(ForeignKey("roadmap_templates.id"))
    node_key: Mapped[str] = mapped_column(String(80))
    requirement: Mapped[str] = mapped_column(String(160))
    reviewed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="approved")
