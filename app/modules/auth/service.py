from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import InstitutionMembership, MembershipStatus, Session, User, UserRole
from app.modules.audit.service import record_audit_event
from app.modules.auth.security import (
    hash_password,
    hash_secret,
    new_secret,
    normalize_email,
    verify_password,
)


class DuplicateEmailError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedSession:
    user: User
    token: str
    csrf_token: str
    membership: InstitutionMembership | None


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
) -> AuthenticatedSession:
    normalized = normalize_email(email)
    user = await db.scalar(select(User).where(User.email == normalized, User.is_active.is_(True)))
    if user is None or not verify_password(user.password_hash, password):
        raise InvalidCredentialsError
    token, csrf_token = new_secret(), new_secret()
    now = datetime.now(UTC)
    membership = await db.scalar(
        select(InstitutionMembership)
        .where(
            InstitutionMembership.user_id == user.id,
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
        )
        .order_by(InstitutionMembership.created_at, InstitutionMembership.id)
        .limit(1)
    )
    session = Session(
        user_id=user.id,
        active_membership_id=membership.id if membership is not None else None,
        token_hash=hash_secret(token),
        csrf_hash=hash_secret(csrf_token),
        expires_at=now + timedelta(hours=ttl_hours),
        last_activity_at=now,
        device_summary=(device_summary or "")[:200] or None,
    )
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
    await db.commit()
    return AuthenticatedSession(
        user=user, token=token, csrf_token=csrf_token, membership=membership
    )


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


async def rotate_session_csrf(
    db: AsyncSession, raw_session_token: str | None
) -> str:
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
