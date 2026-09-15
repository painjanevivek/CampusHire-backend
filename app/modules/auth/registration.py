import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.auth import (
    Institution,
    InstitutionDomain,
    InstitutionMembership,
    InstitutionRegistrationRequest,
    MembershipInvitation,
    MembershipStatus,
    RegistrationStatus,
    StudentRegistrationRequest,
    TermsAcceptance,
    User,
    UserRole,
)
from app.models.profile import StudentProfile
from app.modules.audit.service import record_audit_event
from app.modules.auth.security import hash_password_async, hash_secret, new_secret, normalize_email
from app.modules.communications.service import enqueue_email
from app.modules.institutions.lifecycle import ProvisionConflictError, provision_institution


class RegistrationConflictError(Exception):
    pass


class RegistrationTokenError(Exception):
    pass


@dataclass(frozen=True)
class StudentRegistrationResult:
    status: Literal["registered", "registration_unavailable"]
    next_path: str | None = None


def _expired(value: datetime) -> bool:
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized <= datetime.now(UTC)


def _institution_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


async def start_student_registration(
    db: AsyncSession,
    *,
    name: str,
    surname: str,
    dob: date,
    email: str,
    password: str,
    terms_version: str,
    privacy_version: str,
    invitation_code: str | None,
    correlation_id: str | None,
) -> StudentRegistrationResult:
    normalized_email = normalize_email(email)
    invitation: MembershipInvitation | None = None
    if invitation_code:
        invitation = await db.scalar(
            select(MembershipInvitation).where(
                MembershipInvitation.token_hash == hash_secret(invitation_code),
                MembershipInvitation.email == normalized_email,
                MembershipInvitation.role == UserRole.STUDENT.value,
                MembershipInvitation.accepted_at.is_(None),
                MembershipInvitation.revoked_at.is_(None),
            )
        )
        if invitation is not None and _expired(invitation.expires_at):
            invitation = None

    email_domain = normalized_email.rpartition("@")[2]
    domain_record = await db.scalar(
        select(InstitutionDomain)
        .join(Institution, Institution.id == InstitutionDomain.institution_id)
        .where(
            InstitutionDomain.domain == email_domain,
            InstitutionDomain.verification_status == "verified",
            Institution.is_active.is_(True),
        )
    )
    institution_id = (
        invitation.institution_id
        if invitation is not None
        else domain_record.institution_id
        if domain_record is not None
        else None
    )
    attempt = StudentRegistrationRequest(
        email=normalized_email,
        institution_id=institution_id,
        invitation_id=invitation.id if invitation is not None else None,
        status=RegistrationStatus.UNMATCHED.value,
    )
    db.add(attempt)
    await db.flush()
    existing_user = await db.scalar(select(User.id).where(User.email == normalized_email))
    if institution_id is None or existing_user is not None:
        record_audit_event(
            db,
            institution_id=institution_id,
            event_type="registration.student.unmatched",
            resource_type="student_registration_request",
            resource_id=str(attempt.id),
            outcome="denied",
            reason="identity_not_eligible",
            correlation_id=correlation_id,
        )
        await db.commit()
        return StudentRegistrationResult(status="registration_unavailable")

    now = datetime.now(UTC)
    password_hash = await hash_password_async(password)
    attempt.first_name = name
    attempt.surname = surname
    attempt.date_of_birth = dob
    user = User(
        institution_id=institution_id,
        email=normalized_email,
        password_hash=password_hash,
        role=UserRole.STUDENT.value,
    )
    db.add(user)
    await db.flush()
    db.add_all(
        [
            InstitutionMembership(
                institution_id=institution_id,
                user_id=user.id,
                role=UserRole.STUDENT.value,
                status=MembershipStatus.ACTIVE.value,
                verified_at=now,
                verified_by_user_id=(
                    invitation.created_by_user_id
                    if invitation is not None
                    else domain_record.verified_by_user_id
                    if domain_record is not None
                    else None
                ),
            ),
            StudentProfile(
                user_id=user.id,
                institution_id=institution_id,
                full_name=f"{name} {surname}".strip(),
                date_of_birth=dob,
            ),
            TermsAcceptance(
                user_id=user.id,
                invitation_id=invitation.id if invitation is not None else None,
                document_type="terms",
                version=terms_version,
            ),
            TermsAcceptance(
                user_id=user.id,
                invitation_id=invitation.id if invitation is not None else None,
                document_type="privacy",
                version=privacy_version,
            ),
        ]
    )
    attempt.status = RegistrationStatus.ACTIVATED.value
    if invitation is not None:
        invitation.accepted_at = now
    record_audit_event(
        db,
        actor_user_id=user.id,
        institution_id=institution_id,
        event_type="registration.student.completed",
        resource_type="student_registration_request",
        resource_id=str(attempt.id),
        correlation_id=correlation_id,
        details={"identity_source": "invitation" if invitation is not None else "verified_domain"},
    )
    await db.commit()
    return StudentRegistrationResult(status="registered", next_path="/onboarding")


async def start_institution_registration(
    db: AsyncSession,
    *,
    institution_name: str,
    institution_code: str,
    domain: str,
    admin_email: str,
    correlation_id: str | None,
) -> InstitutionRegistrationRequest:
    normalized_email = normalize_email(admin_email)
    normalized_domain = domain.strip().casefold().removeprefix("www.")
    email_domain = normalized_email.rpartition("@")[2]
    if email_domain != normalized_domain and not email_domain.endswith(f".{normalized_domain}"):
        raise RegistrationConflictError("institutional_email_required")
    normalized_code = institution_code.strip().casefold()
    normalized_name = " ".join(institution_name.split())
    existing_request = await db.scalar(
        select(InstitutionRegistrationRequest.id).where(
            InstitutionRegistrationRequest.admin_email == normalized_email,
            InstitutionRegistrationRequest.status.in_(
                (
                    RegistrationStatus.VERIFICATION_PENDING.value,
                    RegistrationStatus.PENDING_APPROVAL.value,
                    RegistrationStatus.DUPLICATE_REVIEW.value,
                )
            ),
        )
    )
    if existing_request is not None:
        raise RegistrationConflictError("registration_already_exists")
    duplicate = await db.scalar(
        select(Institution.id).where(
            or_(
                func.lower(Institution.code) == normalized_code,
                func.lower(Institution.name) == normalized_name.casefold(),
            )
        )
    ) or await db.scalar(
        select(InstitutionDomain.id).where(InstitutionDomain.domain == normalized_domain)
    )
    pending_duplicate = await db.scalar(
        select(InstitutionRegistrationRequest.id).where(
            InstitutionRegistrationRequest.status != RegistrationStatus.REJECTED.value,
            or_(
                InstitutionRegistrationRequest.institution_code == normalized_code,
                InstitutionRegistrationRequest.domain == normalized_domain,
            ),
        )
    )
    known_names = list(
        (
            await db.scalars(
                select(Institution.name).order_by(Institution.created_at.desc()).limit(500)
            )
        ).all()
    )
    known_names.extend(
        (
            await db.scalars(
                select(InstitutionRegistrationRequest.institution_name)
                .where(InstitutionRegistrationRequest.status != RegistrationStatus.REJECTED.value)
                .order_by(InstitutionRegistrationRequest.created_at.desc())
                .limit(500)
            )
        ).all()
    )
    name_key = _institution_name_key(normalized_name)
    similar_name = any(
        SequenceMatcher(None, name_key, _institution_name_key(candidate)).ratio() >= 0.9
        for candidate in known_names
    )
    raw_token = new_secret()
    item = InstitutionRegistrationRequest(
        institution_name=normalized_name,
        institution_code=normalized_code,
        domain=normalized_domain,
        admin_email=normalized_email,
        duplicate_detected=duplicate is not None or pending_duplicate is not None or similar_name,
        token_hash=hash_secret(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().invitation_ttl_hours),
    )
    db.add(item)
    await db.flush()
    frontend = str(get_settings().frontend_origins[0]).rstrip("/")
    await enqueue_email(
        db,
        institution_id=None,
        recipient_email=normalized_email,
        category="account",
        template_key="invitation",
        variables={
            "institution_name": normalized_name,
            "activation_url": f"{frontend}/sign-up/tnp/verify/{raw_token}",
        },
        dedupe_key=f"institution-registration:{item.id}",
    )
    record_audit_event(
        db,
        event_type="registration.institution.started",
        resource_type="institution_registration_request",
        resource_id=str(item.id),
        correlation_id=correlation_id,
        details={"duplicate_detected": item.duplicate_detected},
    )
    await db.commit()
    await db.refresh(item)
    return item


async def verify_institution_registration(
    db: AsyncSession, *, raw_token: str, correlation_id: str | None
) -> InstitutionRegistrationRequest:
    item = await db.scalar(
        select(InstitutionRegistrationRequest)
        .where(InstitutionRegistrationRequest.token_hash == hash_secret(raw_token))
        .with_for_update()
    )
    if (
        item is None
        or item.status != RegistrationStatus.VERIFICATION_PENDING.value
        or _expired(item.expires_at)
    ):
        raise RegistrationTokenError
    item.email_verified_at = datetime.now(UTC)
    item.status = (
        RegistrationStatus.DUPLICATE_REVIEW.value
        if item.duplicate_detected
        else RegistrationStatus.PENDING_APPROVAL.value
    )
    record_audit_event(
        db,
        event_type="registration.institution.email_verified",
        resource_type="institution_registration_request",
        resource_id=str(item.id),
        correlation_id=correlation_id,
        details={"duplicate_detected": item.duplicate_detected},
    )
    await db.commit()
    await db.refresh(item)
    return item


async def decide_institution_registration(
    db: AsyncSession,
    *,
    request_id: UUID,
    approve: bool,
    reason: str | None,
    correlation_id: str | None,
    reviewed_by_user_id: UUID | None = None,
) -> InstitutionRegistrationRequest | None:
    item = await db.scalar(
        select(InstitutionRegistrationRequest)
        .where(InstitutionRegistrationRequest.id == request_id)
        .with_for_update()
    )
    if item is None:
        return None
    allowed = {
        RegistrationStatus.PENDING_APPROVAL.value,
        RegistrationStatus.DUPLICATE_REVIEW.value,
    }
    if item.status not in allowed:
        raise RegistrationConflictError("registration_not_reviewable")
    if not approve:
        if not reason or len(reason.strip()) < 3:
            raise RegistrationConflictError("rejection_reason_required")
        item.status = RegistrationStatus.REJECTED.value
        item.rejection_reason = reason.strip()[:500]
        item.reviewed_at = datetime.now(UTC)
        item.reviewed_by_user_id = reviewed_by_user_id
        record_audit_event(
            db,
            actor_user_id=reviewed_by_user_id,
            event_type="registration.institution.rejected",
            resource_type="institution_registration_request",
            resource_id=str(item.id),
            reason=item.rejection_reason,
            correlation_id=correlation_id,
        )
        await db.commit()
        await db.refresh(item)
        return item
    try:
        provisioned = await provision_institution(
            db,
            code=item.institution_code,
            name=item.institution_name,
            admin_email=item.admin_email,
            correlation_id=correlation_id,
            is_active=False,
            commit=False,
        )
    except ProvisionConflictError as error:
        raise RegistrationConflictError("institution_conflict") from error
    item.institution_id = provisioned.institution.id
    item.status = RegistrationStatus.APPROVED.value
    item.reviewed_at = datetime.now(UTC)
    item.reviewed_by_user_id = reviewed_by_user_id
    db.add(
        InstitutionDomain(
            institution_id=provisioned.institution.id,
            domain=item.domain,
            verification_status="verified",
            verified_at=datetime.now(UTC),
        )
    )
    record_audit_event(
        db,
        actor_user_id=reviewed_by_user_id,
        institution_id=provisioned.institution.id,
        event_type="registration.institution.approved",
        resource_type="institution_registration_request",
        resource_id=str(item.id),
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(item)
    return item
