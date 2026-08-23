from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PublicationStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"
    ARCHIVED = "archived"


class RuleSetStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("institution_id", "name", name="uq_company_institution_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)


class PlacementDrive(Base, TimestampMixin):
    __tablename__ = "placement_drives"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String(160))
    work_mode: Mapped[str] = mapped_column(String(32))
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(
        String(24), default=PublicationStatus.DRAFT.value, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlacementRole(Base, TimestampMixin):
    __tablename__ = "placement_roles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    drive_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_drives.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    employment_type: Mapped[str] = mapped_column(String(40))
    location: Mapped[str] = mapped_column(String(160))
    work_mode: Mapped[str] = mapped_column(String(32))
    salary_display: Mapped[str | None] = mapped_column(String(120), nullable=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        String(24), default=PublicationStatus.DRAFT.value, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EligibilityRuleSet(Base, TimestampMixin):
    __tablename__ = "eligibility_rule_sets"
    __table_args__ = (
        UniqueConstraint("role_id", "version", name="uq_eligibility_rule_role_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_roles.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default=RuleSetStatus.DRAFT.value, index=True)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EligibilityEvaluation(Base):
    __tablename__ = "eligibility_evaluations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_roles.id", ondelete="RESTRICT"), index=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    rule_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("eligibility_rule_sets.id", ondelete="RESTRICT"), index=True
    )
    facts_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Application(Base, TimestampMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("student_user_id", "role_id", name="uq_application_student_role"),
        UniqueConstraint(
            "institution_id",
            "student_user_id",
            "idempotency_key",
            name="uq_application_idempotency",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_roles.id", ondelete="RESTRICT"), index=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    resume_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="RESTRICT"), index=True
    )
    eligibility_evaluation_id: Mapped[UUID] = mapped_column(
        ForeignKey("eligibility_evaluations.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    role_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    resume_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    facts_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    eligibility_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)


class ApplicationStatusEvent(Base):
    __tablename__ = "application_status_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), index=True)
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ApplicationOverride(Base):
    __tablename__ = "application_overrides"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    previous_status: Mapped[str] = mapped_column(String(32))
    target_status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(500))
    policy_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SavedOpportunity(Base):
    __tablename__ = "saved_opportunities"
    __table_args__ = (
        UniqueConstraint("student_user_id", "role_id", name="uq_saved_opportunity_student_role"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    student_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_roles.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
