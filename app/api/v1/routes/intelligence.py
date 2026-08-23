from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai.providers.gemini import GeminiProvider
from app.core.config import get_settings
from app.models.auth import UserRole
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentTenant,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.intelligence.schemas import (
    ExtractionCreate,
    ExtractionResponse,
    ExtractionReview,
    PolicyAnswer,
    PolicyCreate,
    PolicyQuestion,
    PolicyResponse,
    PolicyReview,
    SemanticMatchResponse,
)
from app.modules.intelligence.service import (
    IntelligenceError,
    answer_policy_question,
    create_extraction,
    create_policy,
    list_extractions,
    list_policies,
    review_extraction,
    review_policy,
    semantic_match,
)

student_router = APIRouter(dependencies=[Depends(require_roles(UserRole.STUDENT.value))])
admin_router = APIRouter(
    prefix="/admin/intelligence",
    dependencies=[Depends(require_roles(UserRole.TNP_ADMIN.value))],
)


def _error(error: IntelligenceError) -> HTTPException:
    code = str(error)
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND
        if code.endswith("_not_found")
        else status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=code,
    )


def _provider() -> GeminiProvider | None:
    if not get_settings().gemini_api_key:
        return None
    try:
        return GeminiProvider()
    except RuntimeError:
        return None


@student_router.get("/opportunities/{role_id}/match", response_model=SemanticMatchResponse)
async def read_semantic_match(
    role_id: UUID, db: Database, tenant: CurrentTenant
) -> SemanticMatchResponse:
    try:
        response = await semantic_match(
            db,
            institution_id=tenant.institution_id,
            student_user_id=tenant.user_id,
            role_id=role_id,
            embedder=_provider(),
        )
    except IntelligenceError as error:
        raise _error(error) from error
    await db.commit()
    return response


@admin_router.get("/policies", response_model=list[PolicyResponse])
async def read_policies(db: Database, principal: CurrentPrincipal) -> list[PolicyResponse]:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    return await list_policies(db, principal.institution_id)


@admin_router.post(
    "/policies",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def add_policy(
    payload: PolicyCreate, request: Request, db: Database, principal: CurrentPrincipal
) -> PolicyResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    item = await create_policy(db, principal.institution_id, principal.user.id, payload)
    record_audit_event(
        db,
        event_type="policy.created",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="policy_document",
        resource_id=str(item.id),
        correlation_id=request.state.correlation_id,
        details={"version": item.version, "section_count": len(item.sections)},
    )
    await db.commit()
    await db.refresh(item)
    return PolicyResponse.model_validate(item, from_attributes=True)


@admin_router.post(
    "/policies/{policy_id}/review",
    response_model=PolicyResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def decide_policy(
    policy_id: UUID,
    payload: PolicyReview,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> PolicyResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    try:
        item = await review_policy(
            db, principal.institution_id, principal.user.id, policy_id, payload
        )
    except IntelligenceError as error:
        raise _error(error) from error
    record_audit_event(
        db,
        event_type=f"policy.{payload.action}",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="policy_document",
        resource_id=str(item.id),
        reason=payload.reason,
        correlation_id=request.state.correlation_id,
        details={"version": item.version},
    )
    await db.commit()
    await db.refresh(item)
    return PolicyResponse.model_validate(item, from_attributes=True)


@admin_router.post("/policies/query", response_model=PolicyAnswer)
async def query_policy(
    payload: PolicyQuestion, db: Database, principal: CurrentPrincipal
) -> PolicyAnswer:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    return await answer_policy_question(db, principal.institution_id, payload)


@admin_router.get("/roles/{role_id}/extractions", response_model=list[ExtractionResponse])
async def read_extractions(
    role_id: UUID, db: Database, principal: CurrentPrincipal
) -> list[ExtractionResponse]:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    return await list_extractions(db, principal.institution_id, role_id)


@admin_router.post(
    "/roles/{role_id}/extractions",
    response_model=ExtractionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def add_extraction(
    role_id: UUID,
    payload: ExtractionCreate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> ExtractionResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    try:
        item = await create_extraction(
            db, principal.institution_id, principal.user.id, role_id, payload
        )
    except IntelligenceError as error:
        raise _error(error) from error
    record_audit_event(
        db,
        event_type="role_extraction.proposed",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="role_extraction",
        resource_id=str(item.id),
        correlation_id=request.state.correlation_id,
        details={"provider": item.provider_name, "prompt_version": item.prompt_version},
    )
    await db.commit()
    await db.refresh(item)
    return ExtractionResponse.model_validate(item, from_attributes=True)


@admin_router.post(
    "/extractions/{proposal_id}/review",
    response_model=ExtractionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def decide_extraction(
    proposal_id: UUID,
    payload: ExtractionReview,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> ExtractionResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    try:
        item = await review_extraction(
            db, principal.institution_id, principal.user.id, proposal_id, payload
        )
    except IntelligenceError as error:
        raise _error(error) from error
    record_audit_event(
        db,
        event_type=f"role_extraction.{payload.action}",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="role_extraction",
        resource_id=str(item.id),
        reason=payload.reason,
        correlation_id=request.state.correlation_id,
        details={"role_id": str(item.role_id), "model_version": item.model_version},
    )
    await db.commit()
    await db.refresh(item)
    return ExtractionResponse.model_validate(item, from_attributes=True)
