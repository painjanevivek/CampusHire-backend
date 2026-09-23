from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class StudentEducation(Base, TimestampMixin):
    __tablename__ = "student_education"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True
    )
    qualification_level: Mapped[str] = mapped_column(String(32))
    degree: Mapped[str] = mapped_column(String(120))
    branch: Mapped[str] = mapped_column(String(120))
    institution: Mapped[str] = mapped_column(String(200))
    start_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graduation_year: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    score_scale: Mapped[str] = mapped_column(String(24))
    active_backlogs: Mapped[int] = mapped_column(Integer, default=0)


class StudentExperience(Base, TimestampMixin):
    __tablename__ = "student_experiences"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True
    )
    organization: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(160))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(default=False)
    responsibilities: Mapped[list[str]] = mapped_column(JSON, default=list)


class StudentProject(Base, TimestampMixin):
    __tablename__ = "student_projects"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(160))
    project_type: Mapped[str] = mapped_column(String(24), default="other", server_default="other")
    description: Mapped[str] = mapped_column(String(2000))
    technologies: Mapped[list[str]] = mapped_column(JSON, default=list)
    outcomes: Mapped[list[str]] = mapped_column(JSON, default=list)
    project_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class StudentCertification(Base, TimestampMixin):
    __tablename__ = "student_certifications"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    issuer: Mapped[str] = mapped_column(String(200))
    issued_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    credential_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class StudentCareerPreference(Base, TimestampMixin):
    __tablename__ = "student_career_preferences"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    target_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    industries: Mapped[list[str]] = mapped_column(JSON, default=list)
    locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    job_types: Mapped[list[str]] = mapped_column(JSON, default=list)
    work_modes: Mapped[list[str]] = mapped_column(JSON, default=list)


class StudentPlacementParticipation(Base, TimestampMixin):
    __tablename__ = "student_placement_participation"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    placement_cycle: Mapped[str] = mapped_column(String(120))
    communication_channels: Mapped[list[str]] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(32))
    privacy_accepted: Mapped[bool] = mapped_column(default=False)
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InstitutionOnboarding(Base, TimestampMixin):
    __tablename__ = "institution_onboarding"

    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    completed_steps: Mapped[list[int]] = mapped_column(JSON, default=list)
    step_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InstitutionCampus(Base, TimestampMixin):
    __tablename__ = "institution_campuses"
    __table_args__ = (
        UniqueConstraint("institution_id", "name", name="uq_institution_campus_name"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))


class InstitutionProgram(Base, TimestampMixin):
    __tablename__ = "institution_programs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    campus_id: Mapped[UUID] = mapped_column(
        ForeignKey("institution_campuses.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    branches: Mapped[list[str]] = mapped_column(JSON, default=list)
    graduating_batches: Mapped[list[int]] = mapped_column(JSON, default=list)


class InstitutionFeatureFlags(Base, TimestampMixin):
    __tablename__ = "institution_feature_flags"

    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), primary_key=True
    )
    ai_generation: Mapped[bool] = mapped_column(default=False)
    ai_resume_studio: Mapped[bool] = mapped_column(default=False)
    student_copilot: Mapped[bool] = mapped_column(default=False)
    tnp_copilot: Mapped[bool] = mapped_column(default=False)
    agent_runs: Mapped[bool] = mapped_column(default=False)
    live_sources: Mapped[bool] = mapped_column(default=False)
    practice_aggregates: Mapped[bool] = mapped_column(default=False)
