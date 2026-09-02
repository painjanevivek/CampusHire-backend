from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class ResumeSource(StrEnum):
    UPLOAD = "upload"
    GENERATED = "generated"


class ResumeStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanStatus(StrEnum):
    QUARANTINED = "quarantined"
    CLEAN = "clean"
    INFECTED = "infected"
    FAILED = "scan_failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    CANCELLATION_REQUESTED = "cancellation_requested"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class Resume(Base, TimestampMixin):
    __tablename__ = "resumes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    latest_version_number: Mapped[int] = mapped_column(Integer, default=0)
    versions: Mapped[list["ResumeVersion"]] = relationship(back_populates="resume")


class ResumeVersion(Base):
    __tablename__ = "resume_versions"
    __table_args__ = (
        UniqueConstraint("user_id", "checksum", name="uq_resume_user_checksum"),
        UniqueConstraint("resume_id", "version_number", name="uq_resume_version_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    resume_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("resumes.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default=ResumeSource.UPLOAD.value)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    original_name: Mapped[str] = mapped_column(String(200))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    content_type: Mapped[str] = mapped_column(String(80), default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(24), default=ResumeStatus.QUEUED.value, index=True
    )
    scan_status: Mapped[str] = mapped_column(
        String(24), default=ScanStatus.QUARANTINED.value, index=True
    )
    scan_engine: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_class: Mapped[str] = mapped_column(String(40), default="active_resume")
    page_count: Mapped[int | None] = mapped_column(nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_revision: Mapped[int] = mapped_column(Integer, default=0)
    review_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    resume: Mapped[Resume | None] = relationship(back_populates="versions")
    processing_job: Mapped["ResumeProcessingJob | None"] = relationship(
        back_populates="resume_version", uselist=False
    )
    suggestions: Mapped[list["ResumeSuggestion"]] = relationship(back_populates="resume_version")


class ResumeProcessingJob(Base, TimestampMixin):
    __tablename__ = "resume_processing_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    resume_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default=JobStatus.QUEUED.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    claimed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resume_version: Mapped[ResumeVersion] = relationship(back_populates="processing_job")
    events: Mapped[list["ResumeJobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class ResumeJobEvent(Base):
    """Append-only, PII-minimized operational history for a resume job."""

    __tablename__ = "resume_job_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("resume_processing_jobs.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    job: Mapped[ResumeProcessingJob] = relationship(back_populates="events")


class ResumeSuggestion(Base, TimestampMixin):
    __tablename__ = "resume_suggestions"
    __table_args__ = (
        UniqueConstraint("resume_version_id", "field_path", name="uq_resume_suggestion_field"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    resume_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="CASCADE"), index=True
    )
    field_path: Mapped[str] = mapped_column(String(160))
    original_text: Mapped[str] = mapped_column(Text)
    proposed_text: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(24), default=SuggestionStatus.PENDING.value, index=True
    )
    decided_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resume_version: Mapped[ResumeVersion] = relationship(back_populates="suggestions")
