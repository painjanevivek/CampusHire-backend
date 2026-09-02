from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth import (
    ADMIN_ROLE_VALUES,
    InstitutionMembership,
    MembershipStatus,
    User,
    UserRole,
)
from app.modules.audit.service import record_audit_event


class MembershipUserNotFoundError(Exception):
    pass


class MembershipPermissionError(Exception):
    pass


async def list_memberships(
    db: AsyncSession,
    institution_id: UUID,
    *,
    role: str | None = None,
) -> list[InstitutionMembership]:
    statement = (
        select(InstitutionMembership)
        .options(selectinload(InstitutionMembership.user))
        .where(InstitutionMembership.institution_id == institution_id)
    )
    if role is not None:
        statement = statement.where(InstitutionMembership.role == role)
    memberships = await db.scalars(
        statement.order_by(InstitutionMembership.created_at, InstitutionMembership.id)
    )
    return list(memberships.all())


async def paginate_memberships(
    db: AsyncSession,
    institution_id: UUID,
    *,
    query: str | None,
    membership_status: str | None,
    role: str | None,
    sort: str,
    page: int,
    page_size: int,
) -> tuple[list[InstitutionMembership], int]:
    statement = select(InstitutionMembership).join(
        User, User.id == InstitutionMembership.user_id
    ).where(InstitutionMembership.institution_id == institution_id)
    if query:
        needle = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                User.email.ilike(needle),
                cast(InstitutionMembership.user_id, String).ilike(needle),
            )
        )
    if membership_status:
        statement = statement.where(InstitutionMembership.status == membership_status)
    if role:
        statement = statement.where(InstitutionMembership.role == role)

    total = (
        await db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    )
    if sort == "status":
        statement = statement.order_by(
            InstitutionMembership.status, User.email, InstitutionMembership.id
        )
    elif sort == "created_at":
        statement = statement.order_by(
            InstitutionMembership.created_at.desc(), InstitutionMembership.id
        )
    else:
        statement = statement.order_by(User.email, InstitutionMembership.id)
    memberships = await db.scalars(
        statement.options(selectinload(InstitutionMembership.user))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(memberships.unique().all()), total


async def verify_membership(
    db: AsyncSession,
    *,
    institution_id: UUID,
    user_id: UUID,
    role: str,
    reason: str,
    actor_user_id: UUID,
    actor_role: str,
    correlation_id: str | None,
) -> InstitutionMembership:
    if role in ADMIN_ROLE_VALUES and actor_role != UserRole.TNP_OWNER.value:
        raise MembershipPermissionError("Only an institution owner can assign administrator roles")
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
        reason=reason,
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
    actor_role: str,
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
    if membership.role in ADMIN_ROLE_VALUES:
        if actor_role != UserRole.TNP_OWNER.value:
            raise MembershipPermissionError(
                "Only an institution owner can change an administrator membership"
            )
        if membership.user_id == actor_user_id:
            raise MembershipPermissionError(
                "Use another institution owner to change your administrator membership"
            )
        if (
            membership.role == UserRole.TNP_OWNER.value
            and membership.status == MembershipStatus.ACTIVE.value
            and status != MembershipStatus.ACTIVE.value
        ):
            active_owner_count = await db.scalar(
                select(func.count())
                .select_from(InstitutionMembership)
                .where(
                    InstitutionMembership.institution_id == institution_id,
                    InstitutionMembership.role == UserRole.TNP_OWNER.value,
                    InstitutionMembership.status == MembershipStatus.ACTIVE.value,
                )
            )
            if (active_owner_count or 0) <= 1:
                raise MembershipPermissionError(
                    "At least one active institution owner must remain"
                )
    previous_status = membership.status
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
        details={"previous_status": previous_status, "status": status, "role": membership.role},
    )
    await db.commit()
    await db.refresh(membership)
    return membership
