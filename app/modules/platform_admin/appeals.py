"""Officer requests to the Platform Admin, separate from student application appeals."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Institution, PlatformAdminAssignment, User
from app.models.communications import TnpPlatformAppeal
from app.models.engagement import InAppNotification
from app.modules.audit.service import record_audit_event


class TnpAppealCreate(BaseModel):
    subject: str = Field(min_length=4, max_length=180)
    description: str = Field(min_length=10, max_length=4000)

    @field_validator("subject", "description")
    @classmethod
    def trim_nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A subject and description are required")
        return value


class TnpAppealStatusUpdate(BaseModel):
    status: str = Field(pattern="^resolved$")


class TnpAppealResponse(BaseModel):
    id: UUID
    institution_name: str
    submitted_by: str
    subject: str
    description: str
    status: str
    created_at: datetime
    resolved_at: datetime | None


class TnpAppealPage(BaseModel):
    items: list[TnpAppealResponse]


def _response(appeal: TnpPlatformAppeal, institution: Institution, user: User) -> TnpAppealResponse:
    return TnpAppealResponse(
        id=appeal.id,
        institution_name=institution.name,
        submitted_by=user.email,
        subject=appeal.subject,
        description=appeal.description,
        status=appeal.status,
        created_at=appeal.created_at,
        resolved_at=appeal.resolved_at,
    )


async def submit_appeal(
    db: AsyncSession, *, institution_id: UUID, user_id: UUID,
    payload: TnpAppealCreate, correlation_id: str | None,
) -> TnpAppealResponse:
    institution = await db.get(Institution, institution_id)
    user = await db.get(User, user_id)
    if institution is None or user is None:
        raise ValueError("An active institution account is required")
    appeal = TnpPlatformAppeal(
        institution_id=institution_id,
        submitted_by_user_id=user_id,
        subject=payload.subject,
        description=payload.description,
    )
    db.add(appeal)
    await db.flush()
    assignment = await db.get(PlatformAdminAssignment, 1)
    if assignment is not None:
        db.add(InAppNotification(
            institution_id=institution_id,
            recipient_user_id=assignment.user_id,
            event_key=f"tnp-platform-appeal:{appeal.id}",
            title=f"T&P appeal: {payload.subject}"[:180],
            body=f"{institution.name} · {user.email}: {payload.description[:500]}",
            deep_link="/admin/notices",
            created_by_user_id=user_id,
            created_at=datetime.now(UTC),
        ))
    record_audit_event(
        db, actor_user_id=user_id, institution_id=institution_id,
        event_type="tnp.platform_appeal.submitted", resource_type="tnp_platform_appeal",
        resource_id=str(appeal.id), correlation_id=correlation_id,
        details={"subject": payload.subject},
    )
    await db.commit()
    await db.refresh(appeal)
    return _response(appeal, institution, user)


async def list_appeals(
    db: AsyncSession, *, submitted_by_user_id: UUID | None = None,
) -> TnpAppealPage:
    statement = (
        select(TnpPlatformAppeal, Institution, User)
        .join(Institution, Institution.id == TnpPlatformAppeal.institution_id)
        .join(User, User.id == TnpPlatformAppeal.submitted_by_user_id)
        .order_by(TnpPlatformAppeal.created_at.desc())
        .limit(100)
    )
    if submitted_by_user_id is not None:
        statement = statement.where(TnpPlatformAppeal.submitted_by_user_id == submitted_by_user_id)
    rows = (await db.execute(statement)).all()
    return TnpAppealPage(
        items=[_response(appeal, institution, user) for appeal, institution, user in rows]
    )


async def resolve_appeal(
    db: AsyncSession, *, appeal_id: UUID, actor_user_id: UUID,
    correlation_id: str | None,
) -> TnpAppealResponse | None:
    result = await db.execute(
        select(TnpPlatformAppeal, Institution, User)
        .join(Institution, Institution.id == TnpPlatformAppeal.institution_id)
        .join(User, User.id == TnpPlatformAppeal.submitted_by_user_id)
        .where(TnpPlatformAppeal.id == appeal_id)
        .with_for_update()
    )
    row = result.first()
    if row is None:
        return None
    appeal, institution, user = row
    if appeal.status != "resolved":
        appeal.status = "resolved"
        appeal.resolved_at = datetime.now(UTC)
        db.add(InAppNotification(
            institution_id=appeal.institution_id,
            recipient_user_id=appeal.submitted_by_user_id,
            event_key=f"tnp-platform-appeal-resolved:{appeal.id}",
            title=f"Appeal resolved: {appeal.subject}"[:180],
            body="The Platform Admin marked your appeal as resolved.",
            deep_link="/tnp/appeal",
            created_by_user_id=actor_user_id,
            created_at=datetime.now(UTC),
        ))
        record_audit_event(
            db, actor_user_id=actor_user_id, institution_id=appeal.institution_id,
            event_type="tnp.platform_appeal.resolved", resource_type="tnp_platform_appeal",
            resource_id=str(appeal.id), correlation_id=correlation_id, details={},
        )
        await db.commit()
        await db.refresh(appeal)
    return _response(appeal, institution, user)
