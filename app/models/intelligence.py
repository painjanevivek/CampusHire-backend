from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETIRED = "retired"


class SemanticMatchEvidence(Base):
    __tablename__ = "semantic_match_evidence"
    __table_args__ = (
        UniqueConstraint("institution_id", "fingerprint", name="uq_semantic_match_fingerprint"),
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
    resume_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("resume_versions.id", ondelete="RESTRICT"), index=True
    )
    profile_revision: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    components: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    explanation: Mapped[list[str]] = mapped_column(JSON, default=list)
    embedding_model: Mapped[str] = mapped_column(String(120))
    embedding_version: Mapped[str] = mapped_column(String(40))
    scoring_version: Mapped[str] = mapped_column(String(40))
    safe_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PolicyDocument(Base, TimestampMixin):
    __tablename__ = "policy_documents"
    __table_args__ = (
        UniqueConstraint("institution_id", "title", "version", name="uq_policy_title_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(240))
    version: Mapped[int] = mapped_column(Integer)
    source_reference: Mapped[str] = mapped_column(String(500))
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default=ReviewStatus.DRAFT.value, index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    review_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoleExtractionProposal(Base, TimestampMixin):
    __tablename__ = "role_extraction_proposals"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), index=True
    )
    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("placement_roles.id", ondelete="CASCADE"), index=True
    )
    source_text_hash: Mapped[str] = mapped_column(String(64))
    proposed_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    proposed_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    provider_name: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default=ReviewStatus.DRAFT.value, index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    review_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
