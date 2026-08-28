from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import InstitutionMembership, MembershipStatus, User
from app.modules.audit.service import record_audit_event


class MembershipUserNotFoundError(Exception):
    pass


async def list_memberships(db: AsyncSession, institution_id: UUID) -> list[InstitutionMembership]:
    memberships = await db.scalars(
        select(InstitutionMembership)
        .options(selectinload(InstitutionMembership.user))
        .where(InstitutionMembership.institution_id == institution_id)
        .order_by(InstitutionMembership.created_at, InstitutionMembership.id)
    )
    return list(memberships.all())


async def verify_membership(
    db: AsyncSession,
    *,
    institution_id: UUID,
    user_id: UUID,
    role: str,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> InstitutionMembership:
    user = await db.scalar(select(User).where(User.id == user_id, User.is_active.is_(True)))
    if user is None:
        raise MembershipUserNotFoundError

    membership = await db.scalar(
        select(InstitutionMembership).where(
            InstitutionMembership.institution_id == institution_id,
            InstitutionMembership.user_id == user_id,
        )
    )
    if membership is None:
        membership = InstitutionMembership(
            institution_id=institution_id,
            user_id=user_id,
            role=role,
        )
        db.add(membership)

    membership.role = role
    membership.status = MembershipStatus.ACTIVE.value
    membership.verified_by_user_id = actor_user_id
    membership.verified_at = datetime.now(UTC)
    await db.flush()
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="membership.verified",
        resource_type="institution_membership",
        resource_id=str(membership.id),
        correlation_id=correlation_id,
        details={"member_user_id": str(user_id), "role": role},
    )
    await db.commit()
    await db.refresh(membership)
    return membership


async def update_membership_status(
    db: AsyncSession,
    *,
    institution_id: UUID,
    membership_id: UUID,
    status: str,
    reason: str,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> InstitutionMembership | None:
    membership = await db.scalar(
        select(InstitutionMembership).where(
            InstitutionMembership.id == membership_id,
            InstitutionMembership.institution_id == institution_id,
        )
    )
    if membership is None:
        return None
    membership.status = status
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="membership.status_changed",
        resource_type="institution_membership",
        resource_id=str(membership.id),
        reason=reason,
        correlation_id=correlation_id,
        details={"status": status},
    )
    await db.commit()
    await db.refresh(membership)
    return membership
