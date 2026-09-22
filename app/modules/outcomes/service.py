from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.outcomes import MetricDefinitionVersion, OutcomeEvent
from app.models.recruitment import Application
from app.modules.outcomes.schemas import (
    MetricDefinitionApproval,
    MetricDefinitionCreate,
    MetricDefinitionResponse,
    OutcomeEventCreate,
    OutcomeEventResponse,
    OutcomeTotals,
)


class OutcomeError(ValueError):
    pass


async def _owned_application(
    db: AsyncSession,
    institution_id: UUID,
    application_id: UUID,
    *,
    student_user_id: UUID | None = None,
) -> Application:
    conditions = [
        Application.id == application_id,
        Application.institution_id == institution_id,
    ]
    if student_user_id is not None:
        conditions.append(Application.student_user_id == student_user_id)
    application = await db.scalar(select(Application).where(*conditions))
    if application is None:
        raise OutcomeError("application_not_found")
    return application


def _response(
    event: OutcomeEvent, superseded_by_event_id: UUID | None = None
) -> OutcomeEventResponse:
    return OutcomeEventResponse(
        id=event.id,
        institution_id=event.institution_id,
        application_id=event.application_id,
        student_user_id=event.student_user_id,
        event_type=event.event_type,
        outcome_state=event.outcome_state,
        event_at=event.event_at,
        source_type=event.source_type,
        source_reference=event.source_reference,
        evidence_reference=event.evidence_reference,
        verified_by_user_id=event.verified_by_user_id,
        verified_at=event.verified_at,
        compensation_amount=event.compensation_amount,
        compensation_currency=event.compensation_currency,
        compensation_period=event.compensation_period,
        stipend_amount=event.stipend_amount,
        joining_date=event.joining_date,
        joining_location=event.joining_location,
        next_update_owner=event.next_update_owner,
        next_update_due_at=event.next_update_due_at,
        supersedes_event_id=event.supersedes_event_id,
        superseded_by_event_id=superseded_by_event_id,
        correction_reason=event.correction_reason,
        created_by_user_id=event.created_by_user_id,
        created_at=event.created_at,
    )


async def create_outcome_event(
    db: AsyncSession,
    institution_id: UUID,
    actor_user_id: UUID,
    application_id: UUID,
    payload: OutcomeEventCreate,
) -> OutcomeEventResponse:
    application = await _owned_application(db, institution_id, application_id)
    if payload.outcome_state == "verified" and not payload.evidence_reference:
        raise OutcomeError("verified_evidence_required")

    if payload.supersedes_event_id is not None:
        original = await db.scalar(
            select(OutcomeEvent).where(
                OutcomeEvent.id == payload.supersedes_event_id,
                OutcomeEvent.institution_id == institution_id,
                OutcomeEvent.application_id == application_id,
            )
        )
        if original is None:
            raise OutcomeError("superseded_event_not_found")
        replacement = await db.scalar(
            select(OutcomeEvent.id).where(
                OutcomeEvent.supersedes_event_id == payload.supersedes_event_id
            )
        )
        if replacement is not None:
            raise OutcomeError("outcome_event_already_superseded")

    now = datetime.now(UTC)
    event = OutcomeEvent(
        institution_id=institution_id,
        application_id=application.id,
        student_user_id=application.student_user_id,
        event_type=payload.event_type,
        outcome_state=payload.outcome_state,
        event_at=payload.event_at,
        source_type=payload.source_type,
        source_reference=payload.source_reference,
        evidence_reference=payload.evidence_reference,
        verified_by_user_id=actor_user_id if payload.outcome_state == "verified" else None,
        verified_at=now if payload.outcome_state == "verified" else None,
        compensation_amount=payload.compensation_amount,
        compensation_currency=payload.compensation_currency,
        compensation_period=payload.compensation_period,
        stipend_amount=payload.stipend_amount,
        joining_date=payload.joining_date,
        joining_location=payload.joining_location,
        next_update_owner=payload.next_update_owner,
        next_update_due_at=payload.next_update_due_at,
        supersedes_event_id=payload.supersedes_event_id,
        correction_reason=payload.correction_reason,
        created_by_user_id=actor_user_id,
        created_at=now,
    )
    db.add(event)
    await db.flush()
    return _response(event)


async def list_outcome_events(
    db: AsyncSession,
    institution_id: UUID,
    application_id: UUID,
    *,
    student_user_id: UUID | None = None,
) -> list[OutcomeEventResponse]:
    await _owned_application(
        db, institution_id, application_id, student_user_id=student_user_id
    )
    events = list(
        (
            await db.scalars(
                select(OutcomeEvent)
                .where(
                    OutcomeEvent.institution_id == institution_id,
                    OutcomeEvent.application_id == application_id,
                )
                .order_by(OutcomeEvent.event_at, OutcomeEvent.created_at, OutcomeEvent.id)
            )
        ).all()
    )
    replacements = {
        event.supersedes_event_id: event.id
        for event in events
        if event.supersedes_event_id is not None
    }
    return [_response(event, replacements.get(event.id)) for event in events]


async def outcome_totals(
    db: AsyncSession,
    institution_id: UUID,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> OutcomeTotals:
    replacement = aliased(OutcomeEvent)
    conditions = [
        OutcomeEvent.institution_id == institution_id,
        ~select(replacement.id)
        .where(replacement.supersedes_event_id == OutcomeEvent.id)
        .exists(),
    ]
    if start_at is not None:
        conditions.append(OutcomeEvent.event_at >= start_at)
    if end_at is not None:
        conditions.append(OutcomeEvent.event_at < end_at)
    rows = (
        await db.execute(
            select(OutcomeEvent.outcome_state, OutcomeEvent.event_type, func.count())
            .where(*conditions)
            .group_by(OutcomeEvent.outcome_state, OutcomeEvent.event_type)
            .order_by(OutcomeEvent.outcome_state, OutcomeEvent.event_type)
        )
    ).all()
    result: dict[str, dict[str, int]] = {"provisional": {}, "verified": {}}
    for state, event_type, count in rows:
        result[state][event_type] = int(count)
    return OutcomeTotals(**result)


async def active_metric_definition(
    db: AsyncSession, code: str, at: datetime
) -> MetricDefinitionResponse | None:
    item = await db.scalar(
        select(MetricDefinitionVersion)
        .where(
            MetricDefinitionVersion.code == code,
            MetricDefinitionVersion.status == "approved",
            MetricDefinitionVersion.effective_at <= at,
        )
        .order_by(
            MetricDefinitionVersion.effective_at.desc(),
            MetricDefinitionVersion.version.desc(),
        )
    )
    return MetricDefinitionResponse.model_validate(item) if item else None


async def create_metric_definition(
    db: AsyncSession,
    actor_user_id: UUID,
    payload: MetricDefinitionCreate,
) -> MetricDefinitionResponse:
    latest_version = await db.scalar(
        select(func.max(MetricDefinitionVersion.version)).where(
            MetricDefinitionVersion.code == payload.code
        )
    )
    item = MetricDefinitionVersion(
        code=payload.code,
        version=int(latest_version or 0) + 1,
        status="draft",
        effective_at=payload.effective_at,
        filters=payload.filters,
        numerator=payload.numerator,
        denominator=payload.denominator,
        exclusions=payload.exclusions,
        evidence_requirements=payload.evidence_requirements,
        notes=payload.notes,
        created_by_user_id=actor_user_id,
    )
    db.add(item)
    await db.flush()
    return MetricDefinitionResponse.model_validate(item)


async def list_metric_definitions(db: AsyncSession) -> list[MetricDefinitionResponse]:
    items = list(
        (
            await db.scalars(
                select(MetricDefinitionVersion).order_by(
                    MetricDefinitionVersion.code,
                    MetricDefinitionVersion.version.desc(),
                )
            )
        ).all()
    )
    return [MetricDefinitionResponse.model_validate(item) for item in items]


async def approve_metric_definition(
    db: AsyncSession,
    definition_id: UUID,
    actor_user_id: UUID,
    payload: MetricDefinitionApproval,
) -> MetricDefinitionResponse:
    item = await db.scalar(
        select(MetricDefinitionVersion)
        .where(MetricDefinitionVersion.id == definition_id)
        .with_for_update()
    )
    if item is None:
        raise OutcomeError("metric_definition_not_found")
    if item.status != payload.expected_status:
        raise OutcomeError("metric_definition_status_conflict")
    item.status = "approved"
    item.approved_by_user_id = actor_user_id
    item.approved_at = datetime.now(UTC)
    item.notes = "\n\n".join(part for part in (item.notes, payload.reason) if part)
    await db.flush()
    return MetricDefinitionResponse.model_validate(item)
