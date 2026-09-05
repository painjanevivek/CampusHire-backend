from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experience import CorrectionEvent, CorrectionRequest
from app.models.recruitment import Application
from app.models.resume import ResumeVersion
from app.modules.experience.schemas import (
    CorrectionEventResponse,
    CorrectionResponse,
    RequestCreate,
    RequestResolution,
    RequestResponseCreate,
)

TERMINAL_STATUSES = {"offered", "rejected", "withdrawn"}


class ExperienceError(ValueError):
    pass


def utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def owned_application(
    db: AsyncSession,
    institution_id: UUID,
    application_id: UUID,
    student_id: UUID | None = None,
    *,
    lock: bool = False,
) -> Application:
    query = select(Application).where(
        Application.id == application_id, Application.institution_id == institution_id
    )
    if student_id is not None:
        query = query.where(Application.student_user_id == student_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    item = await db.scalar(query)
    if item is None:
        raise ExperienceError("application_not_found")
    return item


async def request_response(db: AsyncSession, item: CorrectionRequest) -> CorrectionResponse:
    events = (
        await db.scalars(
            select(CorrectionEvent)
            .where(CorrectionEvent.request_id == item.id)
            .order_by(CorrectionEvent.created_at, CorrectionEvent.id)
        )
    ).all()
    return CorrectionResponse.model_validate(
        {
            "overdue": item.status == "open"
            and item.deadline_at is not None
            and utc(item.deadline_at) < datetime.now(UTC),
            **{
                key: getattr(item, key)
                for key in (
                    "id",
                    "application_id",
                    "instructions",
                    "deadline_at",
                    "status",
                    "revision",
                    "created_at",
                    "updated_at",
                )
            },
            "events": [
                CorrectionEventResponse.model_validate(e, from_attributes=True) for e in events
            ],
        }
    )


async def request_page(
    db: AsyncSession, institution_id: UUID, application_id: UUID, student_id: UUID | None = None
) -> list[CorrectionResponse]:
    await owned_application(db, institution_id, application_id, student_id)
    items = (
        await db.scalars(
            select(CorrectionRequest)
            .where(
                CorrectionRequest.application_id == application_id,
                CorrectionRequest.institution_id == institution_id,
            )
            .order_by(CorrectionRequest.created_at, CorrectionRequest.id)
        )
    ).all()
    return [await request_response(db, item) for item in items]


async def record_request_event(
    db: AsyncSession,
    application: Application,
    item: CorrectionRequest,
    actor_id: UUID,
    action: str,
    body: str,
    resume_id: UUID | None = None,
) -> None:
    from app.modules.audit.service import record_audit_event
    from app.modules.engagement.service import upsert_notification

    db.add(
        CorrectionEvent(
            request_id=item.id,
            actor_user_id=actor_id,
            action=action,
            body=body,
            resume_version_id=resume_id,
            created_at=datetime.now(UTC),
        )
    )
    record_audit_event(
        db,
        event_type=f"application.correction.{action}",
        actor_user_id=actor_id,
        institution_id=application.institution_id,
        resource_type="correction_request",
        resource_id=str(item.id),
        details={"application_id": str(application.id), "revision": item.revision},
    )
    notice = await upsert_notification(
        db,
        institution_id=application.institution_id,
        recipient_user_id=application.student_user_id,
        event_key=f"correction:{item.id}:{item.revision}",
        title="Placement information requested"
        if item.status == "open"
        else "Placement request updated",
        body=body,
        deep_link=f"/applications/{application.id}#request-{item.id}",
        created_by_user_id=actor_id,
    )
    notice.category = "needs_action" if item.status == "open" else "updates"
    notice.related_request_id = item.id
    notice.related_application_id = application.id
    application.revision += 1
    await db.flush()
    await db.refresh(item)


async def create_request(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    application_id: UUID,
    payload: RequestCreate,
) -> CorrectionResponse:
    application = await owned_application(db, institution_id, application_id, lock=True)
    if application.status in TERMINAL_STATUSES:
        raise ExperienceError("application_closed")
    count = await db.scalar(
        select(func.count())
        .select_from(CorrectionRequest)
        .where(CorrectionRequest.application_id == application_id)
    )
    if (count or 0) >= 100:
        raise ExperienceError("application_request_limit")
    item = CorrectionRequest(
        institution_id=institution_id,
        application_id=application_id,
        instructions=payload.instructions,
        deadline_at=payload.deadline_at,
    )
    db.add(item)
    await db.flush()
    await record_request_event(db, application, item, actor_id, "created", payload.instructions)
    return await request_response(db, item)


async def mutable_request(
    db: AsyncSession, application: Application, request_id: UUID, revision: int
) -> CorrectionRequest:
    item = await db.scalar(
        select(CorrectionRequest)
        .where(
            CorrectionRequest.id == request_id,
            CorrectionRequest.application_id == application.id,
            CorrectionRequest.institution_id == application.institution_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise ExperienceError("correction_not_found")
    if item.revision != revision:
        raise ExperienceError("revision_conflict")
    if application.status in TERMINAL_STATUSES or item.status in {"resolved", "cancelled"}:
        raise ExperienceError("request_closed")
    return item


async def respond_to_request(
    db: AsyncSession,
    institution_id: UUID,
    student_id: UUID,
    application_id: UUID,
    request_id: UUID,
    payload: RequestResponseCreate,
) -> CorrectionResponse:
    application = await owned_application(db, institution_id, application_id, student_id, lock=True)
    item = await mutable_request(db, application, request_id, payload.expected_revision)
    if item.status != "open":
        raise ExperienceError("response_already_pending")
    if payload.resume_version_id:
        resume = await db.scalar(
            select(ResumeVersion)
            .where(
                ResumeVersion.id == payload.resume_version_id,
                ResumeVersion.user_id == student_id,
                ResumeVersion.institution_id == institution_id,
                ResumeVersion.status == "completed",
                ResumeVersion.scan_status == "clean",
            )
            .with_for_update()
        )
        if resume is None:
            raise ExperienceError("reviewed_resume_not_found")
    item.status = "awaiting_review"
    item.revision += 1
    await record_request_event(
        db, application, item, student_id, "responded", payload.body, payload.resume_version_id
    )
    return await request_response(db, item)


async def resolve_request(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    application_id: UUID,
    request_id: UUID,
    payload: RequestResolution,
) -> CorrectionResponse:
    application = await owned_application(db, institution_id, application_id, lock=True)
    item = await mutable_request(db, application, request_id, payload.expected_revision)
    if payload.action in {"resolve", "reopen"} and item.status != "awaiting_review":
        raise ExperienceError("response_required")
    item.status = {"resolve": "resolved", "reopen": "open", "cancel": "cancelled"}[payload.action]
    item.revision += 1
    await record_request_event(db, application, item, actor_id, payload.action, payload.body)
    return await request_response(db, item)


async def close_requests(db: AsyncSession, application: Application, actor_id: UUID) -> None:
    if application.status not in TERMINAL_STATUSES:
        return
    items = (
        await db.scalars(
            select(CorrectionRequest)
            .where(
                CorrectionRequest.application_id == application.id,
                CorrectionRequest.status.in_(["open", "awaiting_review"]),
            )
            .order_by(CorrectionRequest.id)
            .with_for_update()
        )
    ).all()
    for item in items:
        item.status = "cancelled"
        item.revision += 1
        await record_request_event(
            db,
            application,
            item,
            actor_id,
            "cancel",
            f"Request closed because the application is {application.status}.",
        )
