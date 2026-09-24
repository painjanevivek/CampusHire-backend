from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.models.auth import UserRole
from app.modules.agentic.schemas import (
    AgentEventResponse,
    AgentRunResponse,
    ArtifactApply,
    ArtifactDecision,
    ArtifactEdit,
    ArtifactResponse,
    EscoSkill,
    PracticeConsentResponse,
    PracticeConsentUpdate,
    RunCancel,
    RunResume,
    SourceReview,
    SourceVersionCreate,
    SourceVersionResponse,
    StudentRunCreate,
    TnpRunCreate,
)
from app.modules.agentic.service import (
    AgentRunConflictError,
    AgentRunNotFoundError,
    AgentRunValidationError,
    apply_drive_artifact,
    cancel_run,
    create_student_run,
    create_tnp_run,
    decide_artifact,
    delete_private_run,
    edit_artifact,
    list_run_events,
    list_runs,
    read_artifact,
    read_consent,
    read_run,
    resume_run,
    update_consent,
)
from app.modules.agentic.sources import (
    SourceValidationError,
    list_sources,
    lookup_esco,
    register_source,
    review_source,
)
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_student_placement_access,
    require_permissions,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.generative.service import GenerationUnavailableError

student_router = APIRouter(
    prefix="/ai/student-copilot",
    dependencies=[
        Depends(require_roles(UserRole.STUDENT.value)),
        Depends(require_student_placement_access),
    ],
)
tnp_router = APIRouter(
    prefix="/ai/tnp-copilot",
    dependencies=[Depends(require_permissions("intelligence.review"))],
)


def _tenant(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution membership required")
    return principal.institution_id


def _raise(error: Exception) -> NoReturn:
    if isinstance(error, AgentRunNotFoundError):
        raise HTTPException(status_code=404, detail="Task or artifact not found") from error
    if isinstance(error, AgentRunConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "revision_conflict",
                "message": "The reviewed record changed. Reload before continuing.",
                "current_revision": error.current_revision,
            },
        ) from error
    if isinstance(error, GenerationUnavailableError):
        raise HTTPException(
            status_code=503,
            detail={"code": str(error), "message": "Agent runs are currently unavailable."},
        ) from error
    if isinstance(error, SourceValidationError) and str(error) in {
        "esco_unavailable", "source_host_unavailable",
    }:
        raise HTTPException(status_code=503, detail={"code": str(error)}) from error
    raise HTTPException(
        status_code=422,
        detail={"code": str(error), "message": "The request could not be completed safely."},
    ) from error


@student_router.post(
    "/runs", response_model=AgentRunResponse, status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def start_student_run(
    payload: StudentRunCreate,
    db: Database,
    principal: CurrentPrincipal,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
) -> AgentRunResponse:
    try:
        return await create_student_run(
            db, institution_id=_tenant(principal), user_id=principal.user.id,
            payload=payload, idempotency_key=idempotency_key,
        )
    except (GenerationUnavailableError, AgentRunValidationError) as error:
        _raise(error)


@tnp_router.post(
    "/runs", response_model=AgentRunResponse, status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def start_tnp_run(
    payload: TnpRunCreate,
    db: Database,
    principal: CurrentPrincipal,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=120),
) -> AgentRunResponse:
    try:
        return await create_tnp_run(
            db, institution_id=_tenant(principal), user_id=principal.user.id,
            payload=payload, idempotency_key=idempotency_key,
        )
    except (GenerationUnavailableError, AgentRunConflictError, AgentRunValidationError) as error:
        _raise(error)


async def _read_run(
    run_id: UUID, db: Database, principal: CurrentPrincipal, audience: str
) -> AgentRunResponse:
    try:
        return await read_run(
            db, run_id=run_id, institution_id=_tenant(principal), user_id=principal.user.id,
            audience=audience,
        )
    except AgentRunNotFoundError as error:
        _raise(error)


@student_router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_student_run(
    run_id: UUID, db: Database, principal: CurrentPrincipal
) -> AgentRunResponse:
    return await _read_run(run_id, db, principal, "student")


@student_router.get("/runs", response_model=list[AgentRunResponse])
async def get_student_runs(
    db: Database,
    principal: CurrentPrincipal,
    target_id: Annotated[UUID | None, Query()] = None,
) -> list[AgentRunResponse]:
    return await list_runs(
        db,
        institution_id=_tenant(principal),
        user_id=principal.user.id,
        audience="student",
        target_id=target_id,
    )


@tnp_router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_tnp_run(run_id: UUID, db: Database, principal: CurrentPrincipal) -> AgentRunResponse:
    return await _read_run(run_id, db, principal, "tnp")


@tnp_router.get("/runs", response_model=list[AgentRunResponse])
async def get_tnp_runs(
    db: Database,
    principal: CurrentPrincipal,
    target_id: Annotated[UUID | None, Query()] = None,
) -> list[AgentRunResponse]:
    return await list_runs(
        db,
        institution_id=_tenant(principal),
        user_id=principal.user.id,
        audience="tnp",
        target_id=target_id,
    )


async def _events(
    run_id: UUID, after: int, db: Database, principal: CurrentPrincipal, audience: str
) -> list[AgentEventResponse]:
    try:
        return await list_run_events(
            db, run_id=run_id, institution_id=_tenant(principal), user_id=principal.user.id,
            audience=audience, after=after,
        )
    except AgentRunNotFoundError as error:
        _raise(error)


@student_router.get("/runs/{run_id}/events", response_model=list[AgentEventResponse])
async def get_student_run_events(
    run_id: UUID, db: Database, principal: CurrentPrincipal,
    after: int = Query(default=0, ge=0),
) -> list[AgentEventResponse]:
    return await _events(run_id, after, db, principal, "student")


@tnp_router.get("/runs/{run_id}/events", response_model=list[AgentEventResponse])
async def get_tnp_run_events(
    run_id: UUID, db: Database, principal: CurrentPrincipal,
    after: int = Query(default=0, ge=0),
) -> list[AgentEventResponse]:
    return await _events(run_id, after, db, principal, "tnp")


async def _resume(
    run_id: UUID, payload: RunResume, db: Database, principal: CurrentPrincipal, audience: str
) -> AgentRunResponse:
    try:
        return await resume_run(
            db, run_id=run_id, institution_id=_tenant(principal), user_id=principal.user.id,
            audience=audience, payload=payload,
        )
    except (AgentRunNotFoundError, AgentRunConflictError, AgentRunValidationError) as error:
        _raise(error)


@student_router.post(
    "/runs/{run_id}/resume", response_model=AgentRunResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def resume_student_run(
    run_id: UUID, payload: RunResume, db: Database, principal: CurrentPrincipal
) -> AgentRunResponse:
    return await _resume(run_id, payload, db, principal, "student")


@tnp_router.post(
    "/runs/{run_id}/resume", response_model=AgentRunResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def resume_tnp_run(
    run_id: UUID, payload: RunResume, db: Database, principal: CurrentPrincipal
) -> AgentRunResponse:
    return await _resume(run_id, payload, db, principal, "tnp")


async def _cancel(
    run_id: UUID, payload: RunCancel, db: Database, principal: CurrentPrincipal, audience: str
) -> AgentRunResponse:
    try:
        return await cancel_run(
            db, run_id=run_id, institution_id=_tenant(principal), user_id=principal.user.id,
            audience=audience, payload=payload,
        )
    except (AgentRunNotFoundError, AgentRunConflictError) as error:
        _raise(error)


@student_router.post(
    "/runs/{run_id}/cancel", response_model=AgentRunResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def cancel_student_run(
    run_id: UUID, payload: RunCancel, db: Database, principal: CurrentPrincipal
) -> AgentRunResponse:
    return await _cancel(run_id, payload, db, principal, "student")


@tnp_router.post(
    "/runs/{run_id}/cancel", response_model=AgentRunResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def cancel_tnp_run(
    run_id: UUID, payload: RunCancel, db: Database, principal: CurrentPrincipal
) -> AgentRunResponse:
    return await _cancel(run_id, payload, db, principal, "tnp")


@student_router.delete(
    "/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def delete_student_run(
    run_id: UUID, db: Database, principal: CurrentPrincipal
) -> Response:
    try:
        await delete_private_run(
            db,
            run_id=run_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
        )
    except (AgentRunNotFoundError, AgentRunValidationError) as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _artifact(
    artifact_id: UUID, db: Database, principal: CurrentPrincipal, audience: str
) -> ArtifactResponse:
    try:
        return await read_artifact(
            db, artifact_id=artifact_id, institution_id=_tenant(principal),
            user_id=principal.user.id, audience=audience,
        )
    except AgentRunNotFoundError as error:
        _raise(error)


@student_router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_student_artifact(
    artifact_id: UUID, db: Database, principal: CurrentPrincipal
) -> ArtifactResponse:
    return await _artifact(artifact_id, db, principal, "student")


@tnp_router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_tnp_artifact(
    artifact_id: UUID, db: Database, principal: CurrentPrincipal
) -> ArtifactResponse:
    return await _artifact(artifact_id, db, principal, "tnp")


async def _edit(
    artifact_id: UUID, payload: ArtifactEdit, db: Database,
    principal: CurrentPrincipal, audience: str,
) -> ArtifactResponse:
    try:
        return await edit_artifact(
            db, artifact_id=artifact_id, institution_id=_tenant(principal),
            user_id=principal.user.id, audience=audience, payload=payload,
        )
    except (AgentRunNotFoundError, AgentRunConflictError, AgentRunValidationError) as error:
        _raise(error)


@student_router.put(
    "/artifacts/{artifact_id}", response_model=ArtifactResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_student_artifact(
    artifact_id: UUID, payload: ArtifactEdit, db: Database, principal: CurrentPrincipal
) -> ArtifactResponse:
    return await _edit(artifact_id, payload, db, principal, "student")


@tnp_router.put(
    "/artifacts/{artifact_id}", response_model=ArtifactResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_tnp_artifact(
    artifact_id: UUID, payload: ArtifactEdit, db: Database, principal: CurrentPrincipal
) -> ArtifactResponse:
    return await _edit(artifact_id, payload, db, principal, "tnp")


async def _decide(
    artifact_id: UUID, payload: ArtifactDecision, db: Database,
    principal: CurrentPrincipal, audience: str,
) -> ArtifactResponse:
    try:
        return await decide_artifact(
            db, artifact_id=artifact_id, institution_id=_tenant(principal),
            user_id=principal.user.id, audience=audience, payload=payload,
        )
    except (AgentRunNotFoundError, AgentRunConflictError, AgentRunValidationError) as error:
        _raise(error)


@student_router.post(
    "/artifacts/{artifact_id}/decision", response_model=ArtifactResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def decide_student_artifact(
    artifact_id: UUID, payload: ArtifactDecision, db: Database, principal: CurrentPrincipal
) -> ArtifactResponse:
    return await _decide(artifact_id, payload, db, principal, "student")


@tnp_router.post(
    "/artifacts/{artifact_id}/decision", response_model=ArtifactResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def decide_tnp_artifact(
    artifact_id: UUID, payload: ArtifactDecision, db: Database, principal: CurrentPrincipal
) -> ArtifactResponse:
    return await _decide(artifact_id, payload, db, principal, "tnp")


@tnp_router.post(
    "/artifacts/{artifact_id}/apply", response_model=ArtifactResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def apply_tnp_artifact(
    artifact_id: UUID, payload: ArtifactApply, db: Database, principal: CurrentPrincipal
) -> ArtifactResponse:
    try:
        return await apply_drive_artifact(
            db, artifact_id=artifact_id, institution_id=_tenant(principal), payload=payload,
        )
    except (AgentRunNotFoundError, AgentRunConflictError, AgentRunValidationError) as error:
        _raise(error)


@student_router.get("/practice-consent", response_model=PracticeConsentResponse)
async def get_practice_consent(
    db: Database, principal: CurrentPrincipal
) -> PracticeConsentResponse:
    return await read_consent(db, institution_id=_tenant(principal), student_id=principal.user.id)


@student_router.put(
    "/practice-consent", response_model=PracticeConsentResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def set_practice_consent(
    payload: PracticeConsentUpdate, db: Database, principal: CurrentPrincipal
) -> PracticeConsentResponse:
    return await update_consent(
        db, institution_id=_tenant(principal), student_id=principal.user.id, payload=payload,
    )


@tnp_router.get("/sources", response_model=list[SourceVersionResponse])
async def get_sources(db: Database, principal: CurrentPrincipal) -> list[SourceVersionResponse]:
    return await list_sources(db, _tenant(principal))


@tnp_router.post(
    "/sources", response_model=SourceVersionResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def create_source(
    payload: SourceVersionCreate, db: Database, principal: CurrentPrincipal
) -> SourceVersionResponse:
    try:
        return await register_source(db, institution_id=_tenant(principal), payload=payload)
    except (GenerationUnavailableError, SourceValidationError) as error:
        _raise(error)


@tnp_router.post(
    "/sources/{source_id}/review", response_model=SourceVersionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def decide_source(
    source_id: UUID, payload: SourceReview, db: Database, principal: CurrentPrincipal
) -> SourceVersionResponse:
    try:
        return await review_source(
            db, institution_id=_tenant(principal), source_id=source_id, payload=payload,
        )
    except SourceValidationError as error:
        _raise(error)


@tnp_router.get("/sources/esco", response_model=list[EscoSkill])
async def search_esco(
    db: Database, principal: CurrentPrincipal,
    term: str = Query(min_length=2, max_length=120),
) -> list[EscoSkill]:
    try:
        return await lookup_esco(db, institution_id=_tenant(principal), term=term)
    except (GenerationUnavailableError, SourceValidationError) as error:
        _raise(error)
