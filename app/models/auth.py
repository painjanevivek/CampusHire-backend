from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UserRole(StrEnum):
    STUDENT = "student"
    PLATFORM_ADMIN = "platform_admin"
    TNP_OWNER = "tnp_owner"
    TNP_ADMIN = "tnp_admin"
    TNP_REVIEWER = "tnp_reviewer"
    TNP_AUDITOR = "tnp_auditor"


TNP_ROLE_VALUES = frozenset(
    {
        UserRole.TNP_OWNER.value,
        UserRole.TNP_ADMIN.value,
        UserRole.TNP_REVIEWER.value,
        UserRole.TNP_AUDITOR.value,
    }
)

ADMIN_ROLE_VALUES = frozenset({UserRole.PLATFORM_ADMIN.value, *TNP_ROLE_VALUES})


class MembershipStatus(StrEnum):
    INVITED = "invited"
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    GRADUATED = "graduated"


class RegistrationStatus(StrEnum):
    VERIFICATION_PENDING = "verification_pending"
    PENDING_APPROVAL = "pending_approval"
    DUPLICATE_REVIEW = "duplicate_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNMATCHED = "unmatched"
    ACTIVATION_SENT = "activation_sent"
    ACTIVATED = "activated"


class Institution(Base, TimestampMixin):
    __tablename__ = "institutions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(default=True)
    roadmaps_enabled: Mapped[bool] = mapped_column(default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")


class InstitutionDomain(Base, TimestampMixin):
    __tablename__ = "institution_domains"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class StudentRegistrationRequest(Base, TimestampMixin):
    __tablename__ = "student_registration_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), index=True)
    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    invitation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("membership_invitations.id", ondelete="SET NULL"), nullable=True
    )
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    surname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)


class InstitutionRegistrationRequest(Base, TimestampMixin):
    __tablename__ = "institution_registration_requests"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_name: Mapped[str] = mapped_column(String(200))
    institution_code: Mapped[str] = mapped_column(String(32), index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    admin_email: Mapped[str] = mapped_column(String(320), index=True)
    duplicate_detected: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(
        String(32), default=RegistrationStatus.VERIFICATION_PENDING.value, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="SET NULL"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default=UserRole.STUDENT.value, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    requires_terms_acceptance: Mapped[bool] = mapped_column(default=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sessions: Mapped[list["Session"]] = relationship(back_populates="user")
    memberships: Mapped[list["InstitutionMembership"]] = relationship(
        back_populates="user", foreign_keys="InstitutionMembership.user_id"
    )


class InstitutionMembership(Base, TimestampMixin):
    __tablename__ = "institution_memberships"
    __table_args__ = (
        UniqueConstraint("institution_id", "user_id", name="uq_membership_institution_user"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=MembershipStatus.PENDING.value, index=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user: Mapped[User] = relationship(back_populates="memberships", foreign_keys=[user_id])


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    active_membership_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("institution_memberships.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )
    mfa_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_summary: Mapped[str | None] = mapped_column(String(200), nullable=True)
    user: Mapped[User] = relationship(back_populates="sessions")
    active_membership: Mapped[InstitutionMembership | None] = relationship()


class PlatformAdminAssignment(Base):
    """Singleton assignment for the one active platform administrator."""

    __tablename__ = "platform_admin_assignment"
    __table_args__ = (CheckConstraint("singleton_key = 1", name="ck_platform_admin_singleton_key"),)

    singleton_key: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), unique=True, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    assigned_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PlatformAdminTransfer(Base):
    """Append-only history of platform administrator bootstrap and transfer events."""

    __tablename__ = "platform_admin_transfers"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    previous_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    new_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    transferred_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class PlatformSetting(Base, TimestampMixin):
    """Non-secret platform configuration; credentials remain environment-only."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class MembershipInvitation(Base, TimestampMixin):
    __tablename__ = "membership_invitations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    enrollment_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default=UserRole.STUDENT.value, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resend_count: Mapped[int] = mapped_column(Integer, default=0)


class RosterImport(Base, TimestampMixin):
    __tablename__ = "roster_imports"
    __table_args__ = (
        UniqueConstraint("institution_id", "content_sha256", name="uq_roster_import_content"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    filename: Mapped[str] = mapped_column(String(200))
    content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="previewed", index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invited_rows: Mapped[int] = mapped_column(Integer, default=0)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RosterImportRow(Base):
    __tablename__ = "roster_import_rows"
    __table_args__ = (
        UniqueConstraint("roster_import_id", "row_number", name="uq_roster_import_row_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    roster_import_id: Mapped[UUID] = mapped_column(
        ForeignKey("roster_imports.id", ondelete="CASCADE"), index=True
    )
    row_number: Mapped[int] = mapped_column(Integer)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    enrollment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    invitation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("membership_invitations.id", ondelete="SET NULL"), nullable=True
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class MfaEnrollment(Base):
    __tablename__ = "mfa_enrollments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    encrypted_secret: Mapped[str] = mapped_column(String(512))
    pending_encrypted_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MfaRecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TermsAcceptance(Base):
    __tablename__ = "terms_acceptances"
    __table_args__ = (
        UniqueConstraint("user_id", "document_type", "version", name="uq_terms_acceptance"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    invitation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("membership_invitations.id", ondelete="SET NULL"), nullable=True
    )
    document_type: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    institution_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(32), default="success", index=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
