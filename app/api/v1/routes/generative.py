from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai.providers.base import StructuredGenerator
from app.ai.providers.gemini import GeminiProvider
from app.core.rate_limit import enforce_fixed_window_limit
from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.generative.resume_studio import materialize_resume_version
from app.modules.generative.schemas import (
    ProposalDecisionRequest,
    ProposalEditRequest,
    ProposalResponse,
    ResumeEvidenceResponse,
    ResumeProposalCreate,
    ResumeVersionMaterializeRequest,
)
from app.modules.generative.service import (
    GenerationUnavailableError,
    ProposalConflictError,
    ProposalValidationError,
    collect_resume_evidence,
    create_resume_proposal,
    decide_proposal,
    edit_proposal,
    list_owned_proposals,
    read_proposal,
    require_capability,
)
from app.modules.resumes.schemas import ResumeVersionResponse
from app.modules.resumes.workflow import ResumeWorkflowError, to_response

router = APIRouter(
    prefix="/ai/resume-studio", dependencies=[Depends(require_roles(UserRole.STUDENT.value))]
)


def _generator() -> StructuredGenerator | None:
    try:
        return GeminiProvider()
    except RuntimeError:
        return None


def _raise_ai_error(error: Exception) -> NoReturn:
    if isinstance(error, ProposalConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "proposal_revision_conflict",
                "message": "The proposal changed in another session.",
                "current_revision": error.current_revision,
            },
        ) from error
    if isinstance(error, GenerationUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": str(error),
                "message": "AI drafting is unavailable. Manual resume creation remains available.",
            },
        ) from error
    if isinstance(error, ResumeWorkflowError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "proposal_invalid", "message": str(error)},
    ) from error


def _tenant(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution membership required")
    return principal.institution_id


@router.get("/evidence", response_model=ResumeEvidenceResponse)
async def read_resume_evidence(db: Database, principal: CurrentPrincipal) -> ResumeEvidenceResponse:
    institution_id = _tenant(principal)
    try:
        await require_capability(db, institution_id, "ai_resume_studio")
    except GenerationUnavailableError as error:
        _raise_ai_error(error)
    return ResumeEvidenceResponse(
        evidence=await collect_resume_evidence(
            db, institution_id=institution_id, user_id=principal.user.id
        )
    )


@router.get("/proposals", response_model=list[ProposalResponse])
async def list_resume_proposals(
    db: Database, principal: CurrentPrincipal
) -> list[ProposalResponse]:
    return await list_owned_proposals(
        db, institution_id=_tenant(principal), user_id=principal.user.id
    )


@router.post(
    "/proposals",
    response_model=ProposalResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def generate_resume_proposal(
    payload: ResumeProposalCreate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> ProposalResponse:
    institution_id = _tenant(principal)
    await enforce_fixed_window_limit(
        request,
        namespace="ai-resume-generation",
        identity=f"{institution_id}:{principal.user.id}",
        limit=5,
        unavailable_detail="Resume drafting is temporarily unavailable.",
    )
    try:
        await require_capability(db, institution_id, "ai_resume_studio")
        return await create_resume_proposal(
            db,
            institution_id=institution_id,
            user_id=principal.user.id,
            selected_evidence_ids=payload.selected_evidence_ids,
            purpose_role_id=payload.purpose_role_id,
            generator=_generator(),
            correlation_id=request.state.correlation_id,
        )
    except (GenerationUnavailableError, ProposalValidationError) as error:
        _raise_ai_error(error)


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_resume_proposal(
    proposal_id: UUID, db: Database, principal: CurrentPrincipal
) -> ProposalResponse:
    try:
        return await read_proposal(
            db,
            proposal_id=proposal_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
        )
    except ProposalValidationError as error:
        _raise_ai_error(error)


@router.put(
    "/proposals/{proposal_id}",
    response_model=ProposalResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_resume_proposal(
    proposal_id: UUID,
    payload: ProposalEditRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> ProposalResponse:
    try:
        return await edit_proposal(
            db,
            proposal_id=proposal_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            expected_revision=payload.expected_revision,
            content=payload.content,
        )
    except (ProposalConflictError, ProposalValidationError) as error:
        _raise_ai_error(error)


@router.post(
    "/proposals/{proposal_id}/decision",
    response_model=ProposalResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def review_resume_proposal(
    proposal_id: UUID,
    payload: ProposalDecisionRequest,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> ProposalResponse:
    try:
        return await decide_proposal(
            db,
            proposal_id=proposal_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            expected_revision=payload.expected_revision,
            accept=payload.decision == "accept",
            correlation_id=request.state.correlation_id,
        )
    except (ProposalConflictError, ProposalValidationError) as error:
        _raise_ai_error(error)


@router.post(
    "/proposals/{proposal_id}/versions",
    response_model=ResumeVersionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def create_resume_from_proposal(
    proposal_id: UUID,
    payload: ResumeVersionMaterializeRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeVersionResponse:
    institution_id = _tenant(principal)
    try:
        await require_capability(db, institution_id, "ai_resume_studio")
        version = await materialize_resume_version(
            db,
            proposal_id=proposal_id,
            institution_id=institution_id,
            user_id=principal.user.id,
            account_email=principal.user.email,
            parent_version_id=payload.parent_version_id,
        )
        return to_response(version)
    except (GenerationUnavailableError, ProposalValidationError, ResumeWorkflowError) as error:
        _raise_ai_error(error)
