from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.ai.providers.base import StructuredGenerator
from app.ai.providers.factory import build_copilot_generator
from app.core.rate_limit import enforce_fixed_window_limit
from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_student_placement_access,
    require_permissions,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.copilot.schemas import (
    ConversationCreate,
    ConversationResponse,
    CopilotProposalDecision,
    CopilotProposalEdit,
    CopilotProposalResponse,
    StudentMessageCreate,
    TnpMessageCreate,
)
from app.modules.copilot.service import (
    ConversationNotFoundError,
    add_student_message,
    add_tnp_message,
    create_conversation,
    decide_copilot_proposal,
    delete_conversation,
    edit_copilot_proposal,
    list_conversations,
    read_conversation,
    read_copilot_proposal,
)
from app.modules.generative.service import (
    GenerationUnavailableError,
    ProposalConflictError,
    ProposalValidationError,
)

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


def _generator() -> StructuredGenerator | None:
    try:
        return build_copilot_generator()
    except RuntimeError:
        return None


def _tenant(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution membership required")
    return principal.institution_id


def _raise_error(error: Exception) -> NoReturn:
    if isinstance(error, ConversationNotFoundError):
        raise HTTPException(status_code=404, detail="Conversation not found") from error
    if isinstance(error, ProposalConflictError):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "proposal_revision_conflict",
                "message": "The proposal changed in another session.",
                "current_revision": error.current_revision,
            },
        ) from error
    if isinstance(error, GenerationUnavailableError):
        raise HTTPException(
            status_code=503,
            detail={"code": str(error), "message": "Copilot is temporarily unavailable."},
        ) from error
    raise HTTPException(
        status_code=422,
        detail={"code": "copilot_request_invalid", "message": str(error)},
    ) from error


async def _create(
    payload: ConversationCreate, db: Database, principal: CurrentPrincipal, audience: str
) -> ConversationResponse:
    try:
        return await create_conversation(
            db,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            audience=audience,
            title=payload.title,
        )
    except GenerationUnavailableError as error:
        _raise_error(error)


async def _list(
    db: Database, principal: CurrentPrincipal, audience: str
) -> list[ConversationResponse]:
    try:
        return await list_conversations(
            db,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            audience=audience,
        )
    except GenerationUnavailableError as error:
        _raise_error(error)


@student_router.get("/conversations", response_model=list[ConversationResponse])
async def list_student_conversations(
    db: Database, principal: CurrentPrincipal
) -> list[ConversationResponse]:
    return await _list(db, principal, "student")


@tnp_router.get("/conversations", response_model=list[ConversationResponse])
async def list_tnp_conversations(
    db: Database, principal: CurrentPrincipal
) -> list[ConversationResponse]:
    return await _list(db, principal, "tnp")


@student_router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def create_student_conversation(
    payload: ConversationCreate, db: Database, principal: CurrentPrincipal
) -> ConversationResponse:
    return await _create(payload, db, principal, "student")


@tnp_router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def create_tnp_conversation(
    payload: ConversationCreate, db: Database, principal: CurrentPrincipal
) -> ConversationResponse:
    return await _create(payload, db, principal, "tnp")


async def _read(
    conversation_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
    audience: str,
) -> ConversationResponse:
    try:
        return await read_conversation(
            db,
            conversation_id=conversation_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            audience=audience,
        )
    except ConversationNotFoundError as error:
        _raise_error(error)


@student_router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def read_student_conversation(
    conversation_id: UUID, db: Database, principal: CurrentPrincipal
) -> ConversationResponse:
    return await _read(conversation_id, db, principal, "student")


@tnp_router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def read_tnp_conversation(
    conversation_id: UUID, db: Database, principal: CurrentPrincipal
) -> ConversationResponse:
    return await _read(conversation_id, db, principal, "tnp")


async def _delete(
    conversation_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
    audience: str,
) -> Response:
    try:
        await delete_conversation(
            db,
            conversation_id=conversation_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            audience=audience,
        )
    except ConversationNotFoundError as error:
        _raise_error(error)
    return Response(status_code=204)


@student_router.delete(
    "/conversations/{conversation_id}", dependencies=[Depends(verify_authenticated_csrf)]
)
async def remove_student_conversation(
    conversation_id: UUID, db: Database, principal: CurrentPrincipal
) -> Response:
    return await _delete(conversation_id, db, principal, "student")


@tnp_router.delete(
    "/conversations/{conversation_id}", dependencies=[Depends(verify_authenticated_csrf)]
)
async def remove_tnp_conversation(
    conversation_id: UUID, db: Database, principal: CurrentPrincipal
) -> Response:
    return await _delete(conversation_id, db, principal, "tnp")


@student_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def send_student_message(
    conversation_id: UUID,
    payload: StudentMessageCreate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    institution_id = _tenant(principal)
    await enforce_fixed_window_limit(
        request,
        namespace="student-copilot",
        identity=f"{institution_id}:{principal.user.id}",
        limit=20,
        unavailable_detail="Student Copilot is temporarily unavailable.",
    )
    try:
        return await add_student_message(
            db,
            conversation_id=conversation_id,
            institution_id=institution_id,
            user_id=principal.user.id,
            intent=payload.intent,
            message=payload.message,
            role_id=payload.role_id,
            generator=_generator(),
            correlation_id=request.state.correlation_id,
        )
    except (
        ConversationNotFoundError,
        GenerationUnavailableError,
        ProposalValidationError,
    ) as error:
        _raise_error(error)


@tnp_router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def send_tnp_message(
    conversation_id: UUID,
    payload: TnpMessageCreate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> ConversationResponse:
    institution_id = _tenant(principal)
    await enforce_fixed_window_limit(
        request,
        namespace="tnp-copilot",
        identity=f"{institution_id}:{principal.user.id}",
        limit=20,
        unavailable_detail="T&P Copilot is temporarily unavailable.",
    )
    try:
        return await add_tnp_message(
            db,
            conversation_id=conversation_id,
            institution_id=institution_id,
            user_id=principal.user.id,
            intent=payload.intent,
            message=payload.message,
            generator=_generator(),
            correlation_id=request.state.correlation_id,
        )
    except (
        ConversationNotFoundError,
        GenerationUnavailableError,
        ProposalValidationError,
    ) as error:
        _raise_error(error)


@tnp_router.get("/proposals/{proposal_id}", response_model=CopilotProposalResponse)
async def get_tnp_proposal(
    proposal_id: UUID, db: Database, principal: CurrentPrincipal
) -> CopilotProposalResponse:
    try:
        return await read_copilot_proposal(
            db,
            proposal_id=proposal_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
        )
    except ProposalValidationError as error:
        _raise_error(error)


@tnp_router.put(
    "/proposals/{proposal_id}",
    response_model=CopilotProposalResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_tnp_proposal(
    proposal_id: UUID,
    payload: CopilotProposalEdit,
    db: Database,
    principal: CurrentPrincipal,
) -> CopilotProposalResponse:
    try:
        return await edit_copilot_proposal(
            db,
            proposal_id=proposal_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            expected_revision=payload.expected_revision,
            content=payload.content,
        )
    except (ProposalConflictError, ProposalValidationError) as error:
        _raise_error(error)


@tnp_router.post(
    "/proposals/{proposal_id}/decision",
    response_model=CopilotProposalResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def review_tnp_proposal(
    proposal_id: UUID,
    payload: CopilotProposalDecision,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> CopilotProposalResponse:
    try:
        return await decide_copilot_proposal(
            db,
            proposal_id=proposal_id,
            institution_id=_tenant(principal),
            user_id=principal.user.id,
            expected_revision=payload.expected_revision,
            approve=payload.decision == "approve",
            correlation_id=request.state.correlation_id,
        )
    except (ProposalConflictError, ProposalValidationError) as error:
        _raise_error(error)
