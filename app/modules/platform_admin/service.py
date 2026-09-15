from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.auth import (
    TNP_ROLE_VALUES,
    Institution,
    InstitutionDomain,
    InstitutionMembership,
    InstitutionRegistrationRequest,
    MembershipStatus,
    PlatformAdminAssignment,
    PlatformAdminTransfer,
    PlatformSetting,
    Session,
    User,
    UserRole,
)
from app.models.communications import EmailDelivery, SupportRequest
from app.models.privacy import DataDeletionRequest
from app.models.recruitment import Application, ApplicationAppeal, PlacementDrive
from app.models.resume import ResumeProcessingJob
from app.modules.audit.service import record_audit_event


class PlatformAdminAssignmentError(Exception):
    pass


@dataclass(frozen=True)
class PlatformAdminMigrationPreview:
    nominated_user_id: UUID
    nominated_email: str
    current_admin_user_id: UUID | None
    nominated_membership_ids: tuple[UUID, ...]
    legacy_owner_count: int


async def platform_dashboard_summary(db: AsyncSession) -> dict[str, object]:
    pending_approvals = await db.scalar(
        select(func.count())
        .select_from(InstitutionRegistrationRequest)
        .where(InstitutionRegistrationRequest.status.in_(("pending_approval", "duplicate_review")))
    )
    active_institutions = await db.scalar(
        select(func.count()).select_from(Institution).where(Institution.is_active.is_(True))
    )
    tnp_accounts = await db.scalar(
        select(func.count())
        .select_from(InstitutionMembership)
        .where(
            InstitutionMembership.role.in_(tuple(TNP_ROLE_VALUES)),
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
        )
    )
    unresolved_support = await db.scalar(
        select(func.count()).select_from(SupportRequest).where(SupportRequest.status == "open")
    )
    failed_jobs = await db.scalar(
        select(func.count())
        .select_from(ResumeProcessingJob)
        .where(ResumeProcessingJob.status == "failed")
    )
    overdue_appeals = await db.scalar(
        select(func.count())
        .select_from(ApplicationAppeal)
        .where(
            ApplicationAppeal.status != "resolved",
            ApplicationAppeal.due_at.is_not(None),
            ApplicationAppeal.due_at < datetime.now(UTC),
        )
    )
    reporting_freshness = await db.scalar(select(func.max(Application.updated_at)))
    return {
        "pending_institution_approvals": pending_approvals or 0,
        "active_institutions": active_institutions or 0,
        "tnp_accounts": tnp_accounts or 0,
        "unresolved_service_items": (unresolved_support or 0) + (failed_jobs or 0),
        "overdue_escalations": overdue_appeals or 0,
        "reporting_freshness_at": reporting_freshness,
    }


async def paginate_platform_institutions(
    db: AsyncSession,
    *,
    query: str | None,
    is_active: bool | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, object]], int]:
    statement = select(Institution)
    if query:
        needle = f"%{query.strip()}%"
        statement = statement.where(
            or_(Institution.name.ilike(needle), Institution.code.ilike(needle))
        )
    if is_active is not None:
        statement = statement.where(Institution.is_active.is_(is_active))
    total = await db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    institutions = (
        await db.scalars(
            statement.order_by(Institution.name, Institution.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [await platform_institution_summary(db, institution) for institution in institutions]
    return items, total or 0


async def platform_institution_summary(
    db: AsyncSession, institution: Institution
) -> dict[str, object]:
    staff_count = await db.scalar(
        select(func.count())
        .select_from(InstitutionMembership)
        .where(
            InstitutionMembership.institution_id == institution.id,
            InstitutionMembership.role.in_(tuple(TNP_ROLE_VALUES)),
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
        )
    )
    student_count = await db.scalar(
        select(func.count())
        .select_from(InstitutionMembership)
        .where(
            InstitutionMembership.institution_id == institution.id,
            InstitutionMembership.role == UserRole.STUDENT.value,
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
        )
    )
    application_count = await db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.institution_id == institution.id)
    )
    return {
        "id": institution.id,
        "code": institution.code,
        "name": institution.name,
        "is_active": institution.is_active,
        "timezone": institution.timezone,
        "staff_count": staff_count or 0,
        "student_count": student_count or 0,
        "application_count": application_count or 0,
        "updated_at": institution.updated_at,
    }


async def platform_institution_detail(
    db: AsyncSession, institution_id: UUID
) -> dict[str, object] | None:
    institution = await db.get(Institution, institution_id)
    if institution is None:
        return None
    result = await platform_institution_summary(db, institution)
    domains = (
        await db.scalars(
            select(InstitutionDomain.domain)
            .where(InstitutionDomain.institution_id == institution_id)
            .order_by(InstitutionDomain.domain)
        )
    ).all()
    drive_count = await db.scalar(
        select(func.count())
        .select_from(PlacementDrive)
        .where(PlacementDrive.institution_id == institution_id)
    )
    result.update({"domains": list(domains), "drive_count": drive_count or 0})
    return result


async def change_institution_status(
    db: AsyncSession,
    *,
    institution_id: UUID,
    is_active: bool,
    reason: str,
    actor_user_id: UUID,
    correlation_id: str | None,
    expected_updated_at: datetime | None,
) -> Institution | None:
    institution = await db.scalar(
        select(Institution).where(Institution.id == institution_id).with_for_update()
    )
    if institution is None:
        return None
    if expected_updated_at is not None:
        actual = institution.updated_at
        expected = expected_updated_at
        actual = actual if actual.tzinfo else actual.replace(tzinfo=UTC)
        expected = expected if expected.tzinfo else expected.replace(tzinfo=UTC)
        if actual != expected:
            raise PlatformAdminAssignmentError("The institution changed; refresh and retry")
    previous = institution.is_active
    institution.is_active = is_active
    if previous and not is_active:
        user_ids = select(InstitutionMembership.user_id).where(
            InstitutionMembership.institution_id == institution_id
        )
        await db.execute(
            update(Session)
            .where(Session.user_id.in_(user_ids), Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="platform.institution.status_changed",
        resource_type="institution",
        resource_id=str(institution_id),
        reason=" ".join(reason.split()),
        correlation_id=correlation_id,
        details={"previous_active": previous, "active": is_active},
    )
    await db.commit()
    await db.refresh(institution)
    return institution


async def list_platform_staff_accounts(
    db: AsyncSession, institution_id: UUID
) -> list[dict[str, object]]:
    memberships = (
        await db.scalars(
            select(InstitutionMembership)
            .options(selectinload(InstitutionMembership.user))
            .where(
                InstitutionMembership.institution_id == institution_id,
                InstitutionMembership.role.in_(tuple(TNP_ROLE_VALUES)),
            )
            .order_by(InstitutionMembership.created_at, InstitutionMembership.id)
        )
    ).all()
    return [
        {
            "id": membership.id,
            "institution_id": membership.institution_id,
            "user_id": membership.user_id,
            "username": membership.user.username,
            "email": membership.user.email,
            "role": membership.role,
            "status": membership.status,
            "requires_terms_acceptance": membership.user.requires_terms_acceptance,
        }
        for membership in memberships
    ]


async def platform_report_summary(db: AsyncSession) -> dict[str, object]:
    institution_count = await db.scalar(select(func.count()).select_from(Institution))
    student_count = await db.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.STUDENT.value)
    )
    drive_count = await db.scalar(select(func.count()).select_from(PlacementDrive))
    application_count = await db.scalar(select(func.count()).select_from(Application))
    status_rows = (
        await db.execute(
            select(Application.status, func.count(Application.id))
            .group_by(Application.status)
            .order_by(Application.status)
        )
    ).all()
    return {
        "institution_count": institution_count or 0,
        "student_count": student_count or 0,
        "drive_count": drive_count or 0,
        "application_count": application_count or 0,
        "applications_by_status": {status: count for status, count in status_rows},
        "generated_at": datetime.now(UTC),
        "provisional": True,
    }


async def platform_health_summary(db: AsyncSession) -> dict[str, object]:
    queue_specs = (
        ("Resume processing", ResumeProcessingJob, "status", "created_at"),
        ("Private-data cleanup", DataDeletionRequest, "status", "requested_at"),
        ("Email delivery", EmailDelivery, "status", "created_at"),
    )
    queues: list[dict[str, object]] = []
    is_degraded = False
    for service, model, status_name, created_name in queue_specs:
        status_column = getattr(model, status_name)
        created_column = getattr(model, created_name)
        pending = await db.scalar(
            select(func.count())
            .select_from(model)
            .where(status_column.in_(("pending", "queued", "processing")))
        )
        failed = await db.scalar(
            select(func.count()).select_from(model).where(status_column == "failed")
        )
        is_degraded = is_degraded or bool(failed)
        oldest = await db.scalar(
            select(func.min(created_column)).where(
                status_column.in_(("pending", "queued", "processing"))
            )
        )
        queues.append(
            {
                "service": service,
                "pending": pending or 0,
                "failed": failed or 0,
                "oldest_outstanding_at": oldest,
            }
        )
    return {
        "status": "degraded" if is_degraded else "healthy",
        "queues": queues,
        "checked_at": datetime.now(UTC),
    }


async def platform_settings(db: AsyncSession) -> dict[str, object]:
    settings = get_settings()
    records = (
        await db.scalars(
            select(PlatformSetting).where(
                PlatformSetting.key.in_(
                    ("platform_notice", "service_targets", "feature_availability")
                )
            )
        )
    ).all()
    values = {item.key: item.value for item in records}
    return {
        "ai_provider": settings.copilot_generation_provider,
        "ai_model": (
            settings.openrouter_model
            if settings.copilot_generation_provider == "openrouter"
            else settings.gemini_generation_model
        ),
        "ai_key_configured": bool(
            settings.openrouter_api_key
            if settings.copilot_generation_provider == "openrouter"
            else settings.gemini_api_key
        ),
        "email_configured": bool(settings.email_smtp_host),
        "storage_backend": settings.resume_storage_backend,
        "platform_notice": values.get("platform_notice", {}),
        "service_targets": values.get(
            "service_targets", {"application_review_working_days": 3, "appeal_working_days": 5}
        ),
        "feature_availability": values.get("feature_availability", {}),
    }


async def update_platform_settings(
    db: AsyncSession,
    *,
    values: dict[str, dict[str, object]],
    actor_user_id: UUID,
    correlation_id: str | None,
) -> None:
    for key, value in values.items():
        record = await db.get(PlatformSetting, key)
        if record is None:
            record = PlatformSetting(key=key, value=value, updated_by_user_id=actor_user_id)
            db.add(record)
        else:
            record.value = value
            record.updated_by_user_id = actor_user_id
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        event_type="platform.settings.updated",
        resource_type="platform_settings",
        correlation_id=correlation_id,
        details={"keys": sorted(values)},
    )
    await db.commit()


async def preview_platform_admin_migration(
    db: AsyncSession, *, user_id: UUID
) -> PlatformAdminMigrationPreview:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise PlatformAdminAssignmentError("The nominated user does not exist or is inactive")
    assignment = await db.get(PlatformAdminAssignment, 1)
    memberships = (
        await db.scalars(
            select(InstitutionMembership)
            .where(InstitutionMembership.user_id == user_id)
            .order_by(InstitutionMembership.created_at, InstitutionMembership.id)
        )
    ).all()
    owner_ids = (
        await db.scalars(
            select(InstitutionMembership.id).where(
                InstitutionMembership.role == UserRole.TNP_OWNER.value
            )
        )
    ).all()
    return PlatformAdminMigrationPreview(
        nominated_user_id=user.id,
        nominated_email=user.email,
        current_admin_user_id=assignment.user_id if assignment is not None else None,
        nominated_membership_ids=tuple(item.id for item in memberships),
        legacy_owner_count=len(owner_ids),
    )


async def transfer_platform_admin(
    db: AsyncSession,
    *,
    user_id: UUID,
    reason: str,
    actor_user_id: UUID | None,
    correlation_id: str | None = None,
    expected_revision: int | None = None,
) -> PlatformAdminAssignment:
    normalized_reason = " ".join(reason.split())
    if len(normalized_reason) < 10:
        raise PlatformAdminAssignmentError("A specific transfer reason is required")

    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        raise PlatformAdminAssignmentError("The nominated user does not exist or is inactive")
    assignment = await db.scalar(
        select(PlatformAdminAssignment)
        .where(PlatformAdminAssignment.singleton_key == 1)
        .with_for_update()
    )
    if (
        assignment is not None
        and expected_revision is not None
        and assignment.revision != expected_revision
    ):
        raise PlatformAdminAssignmentError(
            "The Platform Admin assignment changed; refresh and retry"
        )

    previous_user_id = assignment.user_id if assignment is not None else None
    now = datetime.now(UTC)
    if previous_user_id is not None and previous_user_id != user_id:
        previous_user = await db.get(User, previous_user_id)
        if previous_user is not None:
            previous_user.role = UserRole.TNP_ADMIN.value
        await db.execute(
            update(Session)
            .where(Session.user_id == previous_user_id, Session.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    # A platform administrator is deliberately outside every institution tenant.
    await db.execute(
        update(InstitutionMembership)
        .where(
            InstitutionMembership.user_id == user_id,
            InstitutionMembership.status != MembershipStatus.REVOKED.value,
        )
        .values(status=MembershipStatus.REVOKED.value)
    )
    user.role = UserRole.PLATFORM_ADMIN.value
    user.institution_id = None
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    # Legacy institution owners become full Officers; no account is promoted implicitly.
    await db.execute(
        update(InstitutionMembership)
        .where(
            InstitutionMembership.user_id != user_id,
            InstitutionMembership.role == UserRole.TNP_OWNER.value,
        )
        .values(role=UserRole.TNP_ADMIN.value)
    )
    await db.execute(
        update(User)
        .where(User.id != user_id, User.role == UserRole.TNP_OWNER.value)
        .values(role=UserRole.TNP_ADMIN.value)
    )

    if assignment is None:
        assignment = PlatformAdminAssignment(
            singleton_key=1,
            user_id=user_id,
            assigned_by_user_id=actor_user_id,
            assigned_at=now,
        )
        db.add(assignment)
    else:
        assignment.user_id = user_id
        assignment.assigned_by_user_id = actor_user_id
        assignment.assigned_at = now
        assignment.revision += 1

    db.add(
        PlatformAdminTransfer(
            previous_user_id=previous_user_id,
            new_user_id=user_id,
            transferred_by_user_id=actor_user_id,
            reason=normalized_reason,
            created_at=now,
        )
    )
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        event_type="platform_admin.transferred",
        resource_type="platform_admin_assignment",
        resource_id="1",
        reason=normalized_reason,
        correlation_id=correlation_id,
        details={
            "previous_user_id": str(previous_user_id) if previous_user_id else None,
            "new_user_id": str(user_id),
        },
    )
    await db.commit()
    await db.refresh(assignment)
    return assignment
