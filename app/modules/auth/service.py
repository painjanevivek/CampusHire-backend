from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.auth import (
    ADMIN_ROLE_VALUES,
    InstitutionMembership,
    MembershipInvitation,
    MembershipStatus,
    MfaEnrollment,
    MfaRecoveryCode,
    PasswordResetToken,
    Session,
    TermsAcceptance,
    User,
    UserRole,
)
from app.modules.audit.service import record_audit_event
from app.modules.auth.security import (
    decrypt_totp_secret,
    encrypt_totp_secret,
    hash_password,
    hash_secret,
    new_secret,
    new_totp_secret,
    normalize_email,
    verify_password,
    verify_totp,
)
from app.modules.communications.service import enqueue_email, record_product_event


class DuplicateEmailError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class ExpiredOrUsedTokenError(Exception):
    pass


class InvalidMfaCodeError(Exception):
    pass


class MfaReauthenticationRequiredError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    token: str
    csrf_token: str
    membership: InstitutionMembership | None
    next_step: str


async def create_student(db: AsyncSession, email: str, password: str) -> User:
    normalized = normalize_email(email)
    existing = await db.scalar(select(User.id).where(User.email == normalized))
    if existing:
        raise DuplicateEmailError
    user = User(
        email=normalized, password_hash=hash_password(password), role=UserRole.STUDENT.value
    )
    db.add(user)
    await db.flush()
    record_audit_event(
        db,
        actor_user_id=user.id,
        event_type="auth.signup",
        resource_type="user",
        resource_id=str(user.id),
    )
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(
    db: AsyncSession,
    email: str,
    password: str,
    ttl_hours: int,
    device_summary: str | None,
    required_role: str | None = None,
    demo_mfa_bypass: bool = False,
) -> AuthenticatedSession:
    settings = get_settings()
    if demo_mfa_bypass and (
        not settings.is_development or not settings.demo_login_enabled
    ):
        raise ValueError("Demo MFA bypass is unavailable outside an enabled local demo")
    normalized = normalize_email(email)
    user = await db.scalar(select(User).where(User.email == normalized, User.is_active.is_(True)))
    now = datetime.now(UTC)
    if user is None:
        raise InvalidCredentialsError
    locked_until = user.locked_until
    if (
        locked_until is not None
        and (locked_until if locked_until.tzinfo else locked_until.replace(tzinfo=UTC)) > now
    ):
        record_audit_event(
            db,
            actor_user_id=user.id,
            institution_id=user.institution_id,
            event_type="auth.sign_in_blocked",
            resource_type="user",
            resource_id=str(user.id),
            outcome="denied",
            reason="account_locked",
        )
        await db.commit()
        raise InvalidCredentialsError
    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.auth_lockout_attempts:
            user.locked_until = now + timedelta(minutes=settings.auth_lockout_minutes)
            record_audit_event(
                db,
                actor_user_id=user.id,
                institution_id=user.institution_id,
                event_type="auth.account_locked",
                resource_type="user",
                resource_id=str(user.id),
                outcome="denied",
                reason="repeated_failed_sign_in",
            )
        await db.commit()
        raise InvalidCredentialsError
    token, csrf_token = new_secret(), new_secret()
    membership = await db.scalar(
        select(InstitutionMembership)
        .where(
            InstitutionMembership.user_id == user.id,
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
        )
        .order_by(InstitutionMembership.created_at, InstitutionMembership.id)
        .limit(1)
    )
    has_membership = await db.scalar(
        select(InstitutionMembership.id).where(InstitutionMembership.user_id == user.id).limit(1)
    )
    if has_membership is not None and membership is None:
        raise InvalidCredentialsError
    effective_role = membership.role if membership is not None else user.role
    if required_role is not None and effective_role != required_role:
        raise InvalidCredentialsError
    requires_mfa = effective_role in ADMIN_ROLE_VALUES
    bypasses_mfa = requires_mfa and demo_mfa_bypass
    enrollment = await db.scalar(
        select(MfaEnrollment).where(
            MfaEnrollment.user_id == user.id,
            MfaEnrollment.enrolled_at.is_not(None),
            MfaEnrollment.disabled_at.is_(None),
        )
    )
    next_step = "complete"
    if requires_mfa and not bypasses_mfa:
        next_step = "mfa_challenge" if enrollment is not None else "mfa_setup"
    session = Session(
        user_id=user.id,
        active_membership_id=membership.id if membership is not None else None,
        token_hash=hash_secret(token),
        csrf_hash=hash_secret(csrf_token),
        expires_at=now + timedelta(hours=ttl_hours),
        last_activity_at=now,
        device_summary=(device_summary or "")[:200] or None,
        mfa_verified_at=None if requires_mfa and not bypasses_mfa else now,
    )
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.add(session)
    await db.flush()
    record_audit_event(
        db,
        actor_user_id=user.id,
        institution_id=membership.institution_id if membership is not None else user.institution_id,
        event_type="auth.sign_in",
        resource_type="session",
        resource_id=str(session.id),
    )
    if bypasses_mfa:
        record_audit_event(
            db,
            actor_user_id=user.id,
            institution_id=(
                membership.institution_id if membership is not None else user.institution_id
            ),
            event_type="auth.demo_mfa_bypass",
            resource_type="session",
            resource_id=str(session.id),
            reason="development_demo_only",
        )
    await db.commit()
    return AuthenticatedSession(
        user=user,
        token=token,
        csrf_token=csrf_token,
        membership=membership,
        next_step=next_step,
    )


async def accept_invitation(
    db: AsyncSession,
    *,
    raw_token: str,
    password: str,
    terms_version: str,
    privacy_version: str,
    correlation_id: str | None,
) -> User:
    now = datetime.now(UTC)
    invitation = await db.scalar(
        select(MembershipInvitation).where(
            MembershipInvitation.token_hash == hash_secret(raw_token)
        )
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
    ):
        raise ExpiredOrUsedTokenError
    expires_at = invitation.expires_at
    if (expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)) <= now:
        raise ExpiredOrUsedTokenError
    normalized = normalize_email(invitation.email)
    existing = await db.scalar(select(User).where(User.email == normalized))
    if existing is not None:
        raise ExpiredOrUsedTokenError
    user = User(
        email=normalized,
        password_hash=hash_password(password),
        role=invitation.role,
        institution_id=invitation.institution_id,
    )
    db.add(user)
    await db.flush()
    membership = InstitutionMembership(
        institution_id=invitation.institution_id,
        user_id=user.id,
        role=invitation.role,
        status=MembershipStatus.ACTIVE.value,
        verified_at=now,
        verified_by_user_id=invitation.created_by_user_id,
    )
    db.add(membership)
    invitation.accepted_at = now
    db.add_all(
        [
            TermsAcceptance(
                user_id=user.id,
                invitation_id=invitation.id,
                document_type="terms",
                version=terms_version,
            ),
            TermsAcceptance(
                user_id=user.id,
                invitation_id=invitation.id,
                document_type="privacy",
                version=privacy_version,
            ),
        ]
    )
    record_audit_event(
        db,
        actor_user_id=user.id,
        institution_id=invitation.institution_id,
        event_type="invitation.accepted",
        resource_type="membership_invitation",
        resource_id=str(invitation.id),
        correlation_id=correlation_id,
        details={"role": invitation.role},
    )
    await record_product_event(
        db,
        event_name="invitation_accepted",
        route_group="activation",
        institution_id=invitation.institution_id,
        dedupe_key=f"invitation-accepted:{invitation.id}",
    )
    await db.commit()
    await db.refresh(user)
    return user


async def get_invitation(db: AsyncSession, raw_token: str) -> MembershipInvitation:
    invitation = await db.scalar(
        select(MembershipInvitation).where(
            MembershipInvitation.token_hash == hash_secret(raw_token)
        )
    )
    if (
        invitation is None
        or invitation.accepted_at is not None
        or invitation.revoked_at is not None
    ):
        raise ExpiredOrUsedTokenError
    expires_at = invitation.expires_at
    if (expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)) <= datetime.now(UTC):
        raise ExpiredOrUsedTokenError
    return invitation


async def issue_password_reset(
    db: AsyncSession, email: str, correlation_id: str | None
) -> str | None:
    user = await db.scalar(
        select(User).where(User.email == normalize_email(email), User.is_active.is_(True))
    )
    if user is None:
        return None
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    token = new_secret()
    record = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_secret(token),
        expires_at=datetime.now(UTC) + timedelta(minutes=get_settings().password_reset_ttl_minutes),
    )
    db.add(record)
    frontend = str(get_settings().frontend_origins[0]).rstrip("/")
    await enqueue_email(
        db,
        institution_id=user.institution_id,
        recipient_email=user.email,
        category="account",
        template_key="password_reset",
        variables={"reset_url": f"{frontend}/reset-password?token={token}"},
        dedupe_key=f"password-reset:{record.id}",
    )
    record_audit_event(
        db,
        actor_user_id=user.id,
        institution_id=user.institution_id,
        event_type="auth.password_reset_requested",
        resource_type="password_reset_token",
        resource_id=str(record.id),
        correlation_id=correlation_id,
    )
    await db.commit()
    return token


async def confirm_password_reset(
    db: AsyncSession, raw_token: str, password: str, correlation_id: str | None
) -> None:
    now = datetime.now(UTC)
    record = await db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_secret(raw_token))
    )
    if record is None or record.used_at is not None or record.revoked_at is not None:
        raise ExpiredOrUsedTokenError
    expires_at = record.expires_at
    if (expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)) <= now:
        raise ExpiredOrUsedTokenError
    user = await db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise ExpiredOrUsedTokenError
    user.password_hash = hash_password(password)
    record.used_at = now
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    record_audit_event(
        db,
        actor_user_id=user.id,
        institution_id=user.institution_id,
        event_type="auth.password_reset_completed",
        resource_type="user",
        resource_id=str(user.id),
        correlation_id=correlation_id,
    )
    await db.commit()


async def begin_mfa_setup(db: AsyncSession, session: Session) -> str:
    enrollment = await db.scalar(
        select(MfaEnrollment).where(MfaEnrollment.user_id == session.user_id)
    )
    now = datetime.now(UTC)
    active_enrollment = (
        enrollment is not None
        and enrollment.enrolled_at is not None
        and enrollment.disabled_at is None
    )
    if active_enrollment:
        verified_at = session.mfa_verified_at
        normalized = (
            verified_at
            if verified_at is None or verified_at.tzinfo
            else verified_at.replace(tzinfo=UTC)
        )
        if normalized is None or now - normalized > timedelta(minutes=10):
            raise MfaReauthenticationRequiredError
    secret = new_totp_secret()
    if enrollment is None:
        enrollment = MfaEnrollment(
            user_id=session.user_id, encrypted_secret=encrypt_totp_secret(secret)
        )
        db.add(enrollment)
    elif active_enrollment:
        enrollment.pending_encrypted_secret = encrypt_totp_secret(secret)
    else:
        enrollment.encrypted_secret = encrypt_totp_secret(secret)
        enrollment.enrolled_at = None
        enrollment.disabled_at = None
    await db.commit()
    return secret


async def confirm_mfa_setup(db: AsyncSession, session: Session, code: str) -> list[str]:
    enrollment = await db.scalar(
        select(MfaEnrollment).where(MfaEnrollment.user_id == session.user_id)
    )
    now = datetime.now(UTC)
    if enrollment is not None and enrollment.locked_until is not None:
        locked_until = (
            enrollment.locked_until
            if enrollment.locked_until.tzinfo
            else enrollment.locked_until.replace(tzinfo=UTC)
        )
        if locked_until > now:
            raise InvalidMfaCodeError
        enrollment.locked_until = None
        enrollment.failed_attempts = 0
    if (
        enrollment is not None
        and enrollment.pending_encrypted_secret is not None
        and (
            session.mfa_verified_at is None
            or now
            - (
                session.mfa_verified_at
                if session.mfa_verified_at.tzinfo
                else session.mfa_verified_at.replace(tzinfo=UTC)
            )
            > timedelta(minutes=10)
        )
    ):
        raise MfaReauthenticationRequiredError
    if enrollment is None:
        session.mfa_failed_attempts += 1
        await db.commit()
        raise InvalidMfaCodeError
    encrypted = enrollment.pending_encrypted_secret or enrollment.encrypted_secret
    if not verify_totp(decrypt_totp_secret(encrypted), code):
        enrollment.failed_attempts += 1
        session.mfa_failed_attempts += 1
        if enrollment.failed_attempts >= get_settings().mfa_max_attempts:
            enrollment.locked_until = now + timedelta(
                minutes=get_settings().mfa_lockout_minutes
            )
            session.revoked_at = datetime.now(UTC)
        await db.commit()
        raise InvalidMfaCodeError
    if enrollment.pending_encrypted_secret is not None:
        enrollment.encrypted_secret = enrollment.pending_encrypted_secret
        enrollment.pending_encrypted_secret = None
    enrollment.enrolled_at = now
    enrollment.disabled_at = None
    enrollment.failed_attempts = 0
    enrollment.locked_until = None
    session.mfa_verified_at = now
    session.mfa_failed_attempts = 0
    await db.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == session.user_id))
    codes = [f"{new_secret()[:5]}-{new_secret()[:5]}" for _ in range(10)]
    db.add_all(
        [MfaRecoveryCode(user_id=session.user_id, code_hash=hash_secret(code)) for code in codes]
    )
    record_audit_event(
        db,
        actor_user_id=session.user_id,
        institution_id=session.user.institution_id,
        event_type="auth.mfa_enabled",
        resource_type="user",
        resource_id=str(session.user_id),
    )
    await db.commit()
    return codes


async def verify_mfa(db: AsyncSession, session: Session, code: str) -> bool:
    enrollment = await db.scalar(
        select(MfaEnrollment).where(
            MfaEnrollment.user_id == session.user_id,
            MfaEnrollment.enrolled_at.is_not(None),
            MfaEnrollment.disabled_at.is_(None),
        )
    )
    valid = False
    recovery: MfaRecoveryCode | None = None
    now = datetime.now(UTC)
    if enrollment is not None:
        locked_until = enrollment.locked_until
        normalized_lock = (
            locked_until
            if locked_until is None or locked_until.tzinfo
            else locked_until.replace(tzinfo=UTC)
        )
        if normalized_lock is not None and normalized_lock > now:
            raise InvalidMfaCodeError
        if normalized_lock is not None:
            enrollment.locked_until = None
            enrollment.failed_attempts = 0
        valid = verify_totp(decrypt_totp_secret(enrollment.encrypted_secret), code)
        if not valid:
            recovery = await db.scalar(
                select(MfaRecoveryCode).where(
                    MfaRecoveryCode.user_id == session.user_id,
                    MfaRecoveryCode.code_hash == hash_secret(code),
                    MfaRecoveryCode.used_at.is_(None),
                )
            )
            valid = recovery is not None
    if not valid:
        if enrollment is not None:
            enrollment.failed_attempts += 1
        session.mfa_failed_attempts += 1
        if enrollment is not None and enrollment.failed_attempts >= get_settings().mfa_max_attempts:
            enrollment.locked_until = now + timedelta(
                minutes=get_settings().mfa_lockout_minutes
            )
            session.revoked_at = datetime.now(UTC)
            record_audit_event(
                db,
                actor_user_id=session.user_id,
                institution_id=session.user.institution_id,
                event_type="auth.mfa_challenge_locked",
                resource_type="session",
                resource_id=str(session.id),
                outcome="denied",
                reason="repeated_invalid_mfa_code",
            )
        await db.commit()
        raise InvalidMfaCodeError
    session.mfa_verified_at = now
    session.mfa_failed_attempts = 0
    if enrollment is not None:
        enrollment.failed_attempts = 0
        enrollment.locked_until = None
    if recovery is not None:
        recovery.used_at = now
    await db.commit()
    return recovery is not None


async def list_sessions(db: AsyncSession, user_id: UUID) -> list[Session]:
    records = await db.scalars(
        select(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .order_by(Session.created_at.desc(), Session.id)
    )
    return list(records.all())


async def revoke_session_by_id(db: AsyncSession, *, user_id: UUID, session_id: UUID) -> bool:
    session = await db.scalar(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
        )
    )
    if session is None:
        return False
    session.revoked_at = datetime.now(UTC)
    await db.commit()
    return True


async def revoke_session(db: AsyncSession, session: Session) -> None:
    now = datetime.now(UTC)
    session.revoked_at = now
    record_audit_event(
        db,
        actor_user_id=session.user_id,
        institution_id=(
            session.active_membership.institution_id
            if session.active_membership is not None
            else session.user.institution_id
        ),
        event_type="auth.sign_out",
        resource_type="session",
        resource_id=str(session.id),
    )
    await db.commit()


async def revoke_all_sessions(
    db: AsyncSession, user: User, institution_id: UUID | None = None
) -> None:
    now = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    record_audit_event(
        db,
        actor_user_id=user.id,
        institution_id=institution_id if institution_id is not None else user.institution_id,
        event_type="auth.sign_out_all",
        resource_type="user",
        resource_id=str(user.id),
    )
    await db.commit()


async def rotate_session_csrf(db: AsyncSession, raw_session_token: str | None) -> str:
    """Issue an anonymous CSRF token or rotate the token bound to a live session."""
    csrf_token = new_secret()
    if not raw_session_token:
        return csrf_token
    session = await db.scalar(
        select(Session).where(
            Session.token_hash == hash_secret(raw_session_token),
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
    )
    if session is None:
        return csrf_token
    session.csrf_hash = hash_secret(csrf_token)
    await db.commit()
    return csrf_token
