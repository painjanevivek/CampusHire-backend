from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditEvent, Session, User, UserRole
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
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            event_type="auth.signup",
            details={},
            created_at=datetime.now(UTC),
        )
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
    session = Session(
        user_id=user.id,
        token_hash=hash_secret(token),
        csrf_hash=hash_secret(csrf_token),
        expires_at=now + timedelta(hours=ttl_hours),
        last_activity_at=now,
        device_summary=(device_summary or "")[:200] or None,
    )
    db.add(session)
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            institution_id=user.institution_id,
            event_type="auth.sign_in",
            details={},
            created_at=now,
        )
    )
    await db.commit()
    return AuthenticatedSession(user=user, token=token, csrf_token=csrf_token)


async def revoke_session(db: AsyncSession, session: Session) -> None:
    now = datetime.now(UTC)
    session.revoked_at = now
    db.add(
        AuditEvent(
            actor_user_id=session.user_id, event_type="auth.sign_out", details={}, created_at=now
        )
    )
    await db.commit()


async def revoke_all_sessions(db: AsyncSession, user: User) -> None:
    now = datetime.now(UTC)
    await db.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            institution_id=user.institution_id,
            event_type="auth.sign_out_all",
            details={},
            created_at=now,
        )
    )
    await db.commit()
