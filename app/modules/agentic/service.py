import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agentic import (
    AgentEvent,
    AgentRun,
    DrivePreparationArtifact,
    GenerationUsage,
    PracticeConsent,
    PreparationPlan,
)
from app.models.auth import Institution
from app.models.recruitment import PlacementDrive, PlacementRole
from app.modules.agentic.schemas import (
    AgentEventResponse,
    AgentRunResponse,
    ArtifactApply,
    ArtifactDecision,
    ArtifactEdit,
    ArtifactResponse,
    DrivePreparationContent,
    PracticeConsentResponse,
    PracticeConsentUpdate,
    PreparationPlanContent,
    RunCancel,
    RunLimits,
    RunResume,
    StudentRunCreate,
    TnpRunCreate,
)
from app.modules.generative.service import GenerationUnavailableError, require_capability
from app.modules.recruitment.schemas import DriveUpdate
from app.modules.recruitment.service import RecruitmentError, update_drive

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}


class AgentRunNotFoundError(Exception):
    pass


class AgentRunConflictError(Exception):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision


class AgentRunValidationError(Exception):
    pass


def source_fingerprint(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


async def _reserve_budget(db: AsyncSession, institution_id: UUID) -> None:
    settings = get_settings()
    if (
        settings.ai_per_tenant_monthly_budget_cents <= 0
        or settings.ai_input_cost_cents_per_million_tokens <= 0
        or settings.ai_output_cost_cents_per_million_tokens <= 0
    ):
        raise GenerationUnavailableError("budget_not_configured")
    institution = await db.scalar(
        select(Institution).where(Institution.id == institution_id).with_for_update()
    )
    if institution is None:
        raise AgentRunValidationError("institution_not_found")
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    reserved = await db.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (
                            AgentRun.status.in_(TERMINAL_STATUSES),
                            AgentRun.actual_cost_microunits,
                        ),
                        else_=AgentRun.reserved_cost_microunits,
                    )
                ),
                0,
            )
        ).where(
            AgentRun.institution_id == institution_id,
            AgentRun.created_at >= month_start,
        )
    )
    allowance = settings.ai_per_tenant_monthly_budget_cents * 10_000
    if int(reserved or 0) + settings.agent_reserved_cost_microunits > allowance:
        raise GenerationUnavailableError("tenant_budget_exhausted")


async def _append_event(
    db: AsyncSession,
    run: AgentRun,
    event_type: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    next_sequence = int(
        await db.scalar(
            select(func.coalesce(func.max(AgentEvent.sequence), 0)).where(
                AgentEvent.run_id == run.id
            )
        )
        or 0
    ) + 1
    db.add(
        AgentEvent(
            run_id=run.id,
            sequence=next_sequence,
            event_type=event_type,
            summary=summary,
            event_metadata=metadata or {},
            created_at=datetime.now(UTC),
        )
    )


async def create_student_run(
    db: AsyncSession,
    *,
    institution_id: UUID,
    user_id: UUID,
    payload: StudentRunCreate,
    idempotency_key: str,
) -> AgentRunResponse:
    await require_capability(db, institution_id, "agent_runs")
    role = await db.scalar(
        select(PlacementRole).where(
            PlacementRole.id == payload.role_id,
            PlacementRole.institution_id == institution_id,
        )
    )
    if role is None:
        raise AgentRunValidationError("opportunity_not_found")
    return await _create_run(
        db,
        institution_id=institution_id,
        user_id=user_id,
        audience="student",
        workflow="prepare_opportunity",
        target_kind="role",
        target_id=payload.role_id,
        input_payload=payload.model_dump(mode="json"),
        idempotency_key=idempotency_key,
    )


async def create_tnp_run(
    db: AsyncSession,
    *,
    institution_id: UUID,
    user_id: UUID,
    payload: TnpRunCreate,
    idempotency_key: str,
) -> AgentRunResponse:
    await require_capability(db, institution_id, "agent_runs")
    drive = await db.scalar(
        select(PlacementDrive).where(
            PlacementDrive.id == payload.drive_id,
            PlacementDrive.institution_id == institution_id,
        )
    )
    if drive is None:
        raise AgentRunValidationError("drive_not_found")
    if drive.revision != payload.expected_revision:
        raise AgentRunConflictError(drive.revision)
    return await _create_run(
        db,
        institution_id=institution_id,
        user_id=user_id,
        audience="tnp",
        workflow="prepare_drive",
        target_kind="drive",
        target_id=payload.drive_id,
        input_payload=payload.model_dump(mode="json"),
        idempotency_key=idempotency_key,
    )


async def _create_run(
    db: AsyncSession,
    *,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    workflow: str,
    target_kind: str,
    target_id: UUID,
    input_payload: dict[str, Any],
    idempotency_key: str,
) -> AgentRunResponse:
    existing = await db.scalar(
        select(AgentRun).where(
            AgentRun.institution_id == institution_id,
            AgentRun.user_id == user_id,
            AgentRun.workflow == workflow,
            AgentRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return await run_response(db, existing)
    await _reserve_budget(db, institution_id)
    settings = get_settings()
    run = AgentRun(
        institution_id=institution_id,
        user_id=user_id,
        audience=audience,
        workflow=workflow,
        target_kind=target_kind,
        target_id=target_id,
        status="queued",
        idempotency_key=idempotency_key,
        input_payload=input_payload,
        checkpoint_data={"stage": "created", "answers": []},
        reserved_cost_microunits=settings.agent_reserved_cost_microunits,
        expires_at=datetime.now(UTC) + timedelta(days=settings.copilot_retention_days),
    )
    db.add(run)
    await db.flush()
    await _append_event(db, run, "queued", "Preparation task queued.")
    await db.commit()
    await db.refresh(run)
    return await run_response(db, run)


async def authorized_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    lock: bool = False,
) -> AgentRun:
    statement = select(AgentRun).where(
        AgentRun.id == run_id,
        AgentRun.institution_id == institution_id,
        AgentRun.audience == audience,
    )
    if audience == "student":
        statement = statement.where(AgentRun.user_id == user_id)
    if lock:
        statement = statement.with_for_update()
    run = await db.scalar(statement)
    if run is None:
        raise AgentRunNotFoundError()
    return run


async def read_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
) -> AgentRunResponse:
    return await run_response(
        db,
        await authorized_run(
            db,
            run_id=run_id,
            institution_id=institution_id,
            user_id=user_id,
            audience=audience,
        ),
    )


async def list_runs(
    db: AsyncSession,
    *,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    target_id: UUID | None,
) -> list[AgentRunResponse]:
    statement = select(AgentRun).where(
        AgentRun.institution_id == institution_id,
        AgentRun.audience == audience,
    )
    if audience == "student":
        statement = statement.where(AgentRun.user_id == user_id)
    if target_id is not None:
        statement = statement.where(AgentRun.target_id == target_id)
    runs = (
        await db.scalars(statement.order_by(AgentRun.created_at.desc()).limit(50))
    ).all()
    return [await run_response(db, run) for run in runs]


async def list_run_events(
    db: AsyncSession,
    *,
    run_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    after: int,
) -> list[AgentEventResponse]:
    await authorized_run(
        db,
        run_id=run_id,
        institution_id=institution_id,
        user_id=user_id,
        audience=audience,
    )
    events = (
        await db.scalars(
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id, AgentEvent.sequence > after)
            .order_by(AgentEvent.sequence)
            .limit(100)
        )
    ).all()
    return [
        AgentEventResponse(
            sequence=item.sequence,
            event_type=item.event_type,
            summary=item.summary,
            metadata=dict(item.event_metadata),
            created_at=item.created_at,
        )
        for item in events
    ]


async def resume_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    payload: RunResume,
) -> AgentRunResponse:
    run = await authorized_run(
        db,
        run_id=run_id,
        institution_id=institution_id,
        user_id=user_id,
        audience=audience,
        lock=True,
    )
    _expected_revision(run, payload.expected_revision)
    expected_interrupt = (run.required_action or {}).get("interrupt_id")
    if run.status != "awaiting_input" or expected_interrupt != payload.interrupt_id:
        raise AgentRunValidationError("run_not_awaiting_this_input")
    checkpoint = dict(run.checkpoint_data)
    answers = list(checkpoint.get("answers", []))
    answers.append({"interrupt_id": payload.interrupt_id, "response": payload.response})
    checkpoint["answers"] = answers
    checkpoint["stage"] = "resumed"
    run.checkpoint_data = checkpoint
    run.required_action = None
    run.status = "queued"
    run.revision += 1
    await _append_event(db, run, "resumed", "Clarification received; task queued to resume.")
    await db.commit()
    await db.refresh(run)
    return await run_response(db, run)


async def cancel_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    payload: RunCancel,
) -> AgentRunResponse:
    run = await authorized_run(
        db,
        run_id=run_id,
        institution_id=institution_id,
        user_id=user_id,
        audience=audience,
        lock=True,
    )
    _expected_revision(run, payload.expected_revision)
    if run.status in TERMINAL_STATUSES:
        return await run_response(db, run)
    run.cancel_requested = True
    run.status = "cancelled"
    run.required_action = None
    run.revision += 1
    await _append_event(db, run, "cancelled", "Task cancelled. No further model calls will run.")
    await db.commit()
    await db.refresh(run)
    return await run_response(db, run)


async def delete_private_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    institution_id: UUID,
    user_id: UUID,
) -> None:
    """Delete an unaccepted student task and all of its private execution data."""
    run = await authorized_run(
        db,
        run_id=run_id,
        institution_id=institution_id,
        user_id=user_id,
        audience="student",
        lock=True,
    )
    if run.status not in TERMINAL_STATUSES:
        raise AgentRunValidationError("cancel_active_run_before_deleting")
    plan = await db.scalar(
        select(PreparationPlan).where(PreparationPlan.run_id == run.id).with_for_update()
    )
    if plan is not None and plan.status == "accepted":
        raise AgentRunValidationError("accepted_plan_follows_record_retention")
    await db.execute(delete(AgentEvent).where(AgentEvent.run_id == run.id))
    await db.execute(delete(GenerationUsage).where(GenerationUsage.run_id == run.id))
    if plan is not None:
        await db.delete(plan)
    await db.delete(run)
    await db.commit()


async def run_response(db: AsyncSession, run: AgentRun) -> AgentRunResponse:
    settings = get_settings()
    artifact: ArtifactResponse | None = None
    if run.workflow == "prepare_opportunity":
        item = await db.scalar(select(PreparationPlan).where(PreparationPlan.run_id == run.id))
        if item is not None:
            artifact = _plan_response(item)
    else:
        drive_item = await db.scalar(
            select(DrivePreparationArtifact).where(DrivePreparationArtifact.run_id == run.id)
        )
        if drive_item is not None:
            artifact = _drive_response(drive_item)
    return AgentRunResponse(
        id=run.id,
        audience=run.audience,
        workflow=run.workflow,
        target_kind=run.target_kind,
        target_id=run.target_id,
        status=run.status,
        revision=run.revision,
        source_fingerprint=run.source_fingerprint,
        limits=RunLimits(
            model_calls_remaining=max(0, settings.agent_max_model_calls - run.model_calls),
            tool_calls_remaining=max(0, settings.agent_max_tool_calls - run.tool_calls),
            correction_attempts_remaining=max(
                0, settings.agent_max_correction_attempts - run.correction_attempts
            ),
            active_seconds_remaining=max(
                0.0, settings.agent_max_active_seconds - run.active_time_ms / 1_000
            ),
            reserved_cost_microunits=run.reserved_cost_microunits,
            actual_cost_microunits=run.actual_cost_microunits,
        ),
        required_action=run.required_action,
        safe_error=run.safe_error,
        artifact=artifact.model_dump(mode="json") if artifact else None,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


async def read_artifact(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
) -> ArtifactResponse:
    if audience == "student":
        item = await db.scalar(
            select(PreparationPlan).where(
                PreparationPlan.id == artifact_id,
                PreparationPlan.institution_id == institution_id,
                PreparationPlan.student_id == user_id,
            )
        )
        if item is not None:
            return _plan_response(item)
    else:
        drive_item = await db.scalar(
            select(DrivePreparationArtifact).where(
                DrivePreparationArtifact.id == artifact_id,
                DrivePreparationArtifact.institution_id == institution_id,
            )
        )
        if drive_item is not None:
            return _drive_response(drive_item)
    raise AgentRunNotFoundError()


async def edit_artifact(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    payload: ArtifactEdit,
) -> ArtifactResponse:
    if audience == "student":
        item = await db.scalar(
            select(PreparationPlan)
            .where(
                PreparationPlan.id == artifact_id,
                PreparationPlan.institution_id == institution_id,
                PreparationPlan.student_id == user_id,
            )
            .with_for_update()
        )
        if item is None:
            raise AgentRunNotFoundError()
        _artifact_revision(item.revision, payload.expected_revision)
        item.content = PreparationPlanContent.model_validate(payload.content).model_dump(
            mode="json"
        )
        item.revision += 1
        await db.commit()
        await db.refresh(item)
        return _plan_response(item)
    item2 = await db.scalar(
        select(DrivePreparationArtifact)
        .where(
            DrivePreparationArtifact.id == artifact_id,
            DrivePreparationArtifact.institution_id == institution_id,
        )
        .with_for_update()
    )
    if item2 is None:
        raise AgentRunNotFoundError()
    _artifact_revision(item2.revision, payload.expected_revision)
    item2.content = DrivePreparationContent.model_validate(payload.content).model_dump(mode="json")
    item2.revision += 1
    await db.commit()
    await db.refresh(item2)
    return _drive_response(item2)


async def decide_artifact(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    audience: str,
    payload: ArtifactDecision,
) -> ArtifactResponse:
    response = await read_artifact(
        db,
        artifact_id=artifact_id,
        institution_id=institution_id,
        user_id=user_id,
        audience=audience,
    )
    if response.status != "draft":
        raise AgentRunValidationError("artifact_already_decided")
    run = await db.get(AgentRun, response.run_id, with_for_update=True)
    if run is None or run.status != "awaiting_review":
        raise AgentRunValidationError("run_not_awaiting_artifact_review")
    now = datetime.now(UTC)
    if audience == "student":
        plan = await db.get(PreparationPlan, artifact_id, with_for_update=True)
        if plan is None:
            raise AgentRunNotFoundError()
        _artifact_revision(plan.revision, payload.expected_revision)
        plan.status = "accepted" if payload.decision == "accept" else "rejected"
        plan.accepted_at = now if payload.decision == "accept" else None
        plan.rejected_at = now if payload.decision == "reject" else None
        plan.revision += 1
        artifact_run_id = plan.run_id
    else:
        drive_artifact = await db.get(
            DrivePreparationArtifact, artifact_id, with_for_update=True
        )
        if drive_artifact is None:
            raise AgentRunNotFoundError()
        _artifact_revision(drive_artifact.revision, payload.expected_revision)
        drive_artifact.status = (
            "accepted" if payload.decision == "accept" else "rejected"
        )
        drive_artifact.accepted_at = now if payload.decision == "accept" else None
        drive_artifact.rejected_at = now if payload.decision == "reject" else None
        drive_artifact.revision += 1
        artifact_run_id = drive_artifact.run_id
    assert run.id == artifact_run_id
    run.status = "completed"
    run.required_action = None
    run.revision += 1
    await _append_event(
        db,
        run,
        "completed",
        "Proposal accepted." if payload.decision == "accept" else "Proposal rejected.",
    )
    await db.commit()
    if audience == "student":
        assert plan is not None
        await db.refresh(plan)
        return _plan_response(plan)
    assert drive_artifact is not None
    await db.refresh(drive_artifact)
    return _drive_response(drive_artifact)


async def apply_drive_artifact(
    db: AsyncSession,
    *,
    artifact_id: UUID,
    institution_id: UUID,
    payload: ArtifactApply,
) -> ArtifactResponse:
    artifact = await db.scalar(
        select(DrivePreparationArtifact)
        .where(
            DrivePreparationArtifact.id == artifact_id,
            DrivePreparationArtifact.institution_id == institution_id,
        )
        .with_for_update()
    )
    if artifact is None:
        raise AgentRunNotFoundError()
    _artifact_revision(artifact.revision, payload.expected_revision)
    if artifact.status != "accepted":
        raise AgentRunValidationError("artifact_must_be_accepted")
    drive = await db.scalar(
        select(PlacementDrive)
        .where(
            PlacementDrive.id == artifact.drive_id,
            PlacementDrive.institution_id == institution_id,
        )
        .with_for_update()
    )
    if drive is None:
        raise AgentRunValidationError("drive_not_found")
    if (
        drive.revision != payload.expected_drive_revision
        or drive.revision != artifact.source_drive_revision
    ):
        raise AgentRunConflictError(drive.revision)
    selected = set(payload.fields)
    proposals = DrivePreparationContent.model_validate(artifact.content).field_proposals
    proposed_fields = {proposal.field for proposal in proposals}
    if not selected.issubset(proposed_fields):
        raise AgentRunValidationError("selected_field_not_proposed")
    values = {
        proposal.field: proposal.proposed_value
        for proposal in proposals
        if proposal.field in selected
    }
    if not values:
        raise AgentRunValidationError("no_reviewed_fields_selected")
    validated = DriveUpdate.model_validate(values)
    try:
        await update_drive(db, institution_id, artifact.drive_id, validated)
    except RecruitmentError as error:
        raise AgentRunValidationError(str(error)) from error
    artifact.status = "applied"
    artifact.revision += 1
    await db.commit()
    await db.refresh(artifact)
    return _drive_response(artifact)


async def read_consent(
    db: AsyncSession, *, institution_id: UUID, student_id: UUID
) -> PracticeConsentResponse:
    item = await db.scalar(
        select(PracticeConsent).where(
            PracticeConsent.institution_id == institution_id,
            PracticeConsent.student_id == student_id,
            PracticeConsent.purpose == "practice_aggregates",
        )
    )
    if item is None:
        return PracticeConsentResponse(
            purpose="practice_aggregates",
            consent_version="1",
            opted_in=False,
            granted_at=None,
            revoked_at=None,
        )
    return _consent_response(item)


async def update_consent(
    db: AsyncSession,
    *,
    institution_id: UUID,
    student_id: UUID,
    payload: PracticeConsentUpdate,
) -> PracticeConsentResponse:
    now = datetime.now(UTC)
    item = await db.scalar(
        select(PracticeConsent)
        .where(
            PracticeConsent.institution_id == institution_id,
            PracticeConsent.student_id == student_id,
            PracticeConsent.purpose == "practice_aggregates",
        )
        .with_for_update()
    )
    if item is None:
        item = PracticeConsent(
            institution_id=institution_id,
            student_id=student_id,
            purpose="practice_aggregates",
            consent_version=payload.consent_version,
            opted_in=payload.opted_in,
        )
        db.add(item)
    item.consent_version = payload.consent_version
    item.opted_in = payload.opted_in
    item.granted_at = now if payload.opted_in else item.granted_at
    item.revoked_at = None if payload.opted_in else now
    await db.commit()
    await db.refresh(item)
    return _consent_response(item)


def _expected_revision(run: AgentRun, expected: int) -> None:
    if run.revision != expected:
        raise AgentRunConflictError(run.revision)


def _artifact_revision(current: int, expected: int) -> None:
    if current != expected:
        raise AgentRunConflictError(current)


def _plan_response(item: PreparationPlan) -> ArtifactResponse:
    return ArtifactResponse(
        id=item.id,
        run_id=item.run_id,
        kind="preparation_plan",
        target_id=item.role_id,
        status=item.status,
        revision=item.revision,
        content=dict(item.content),
        evidence_references=list(item.evidence_references),
        source_fingerprint=item.source_fingerprint,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _drive_response(item: DrivePreparationArtifact) -> ArtifactResponse:
    return ArtifactResponse(
        id=item.id,
        run_id=item.run_id,
        kind="drive_preparation",
        target_id=item.drive_id,
        status=item.status,
        revision=item.revision,
        content=dict(item.content),
        evidence_references=list(item.evidence_references),
        source_fingerprint=item.source_fingerprint,
        source_target_revision=item.source_drive_revision,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _consent_response(item: PracticeConsent) -> PracticeConsentResponse:
    return PracticeConsentResponse(
        purpose="practice_aggregates",
        consent_version=item.consent_version,
        opted_in=item.opted_in,
        granted_at=item.granted_at,
        revoked_at=item.revoked_at,
    )
