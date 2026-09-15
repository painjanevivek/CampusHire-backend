from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_permissions,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.privacy.schemas import (
    DataDeletionCreate,
    DataDeletionResponse,
    LegalHoldCreate,
    LegalHoldRelease,
    LegalHoldResponse,
    PrivacyRequestCreate,
    PrivacyRequestDecision,
    PrivacyRequestResponse,
)
from app.modules.privacy.service import (
    PrivacyError,
    create_legal_hold,
    create_privacy_request,
    decide_privacy_request,
    list_institution_privacy_requests,
    list_legal_holds,
    list_own_privacy_requests,
    release_legal_hold,
    request_student_deletion,
)

router = APIRouter(prefix="/privacy")
tnp_router = APIRouter(
    prefix="/tnp/privacy",
    dependencies=[Depends(require_permissions("institution.manage"))],
)


@router.get(
    "/requests",
    response_model=list[PrivacyRequestResponse],
    dependencies=[Depends(require_roles(UserRole.STUDENT.value))],
)
async def read_own_requests(
    db: Database, principal: CurrentPrincipal
) -> list[PrivacyRequestResponse]:
    return await list_own_privacy_requests(db, user_id=principal.user.id)


@router.post(
    "/requests",
    response_model=PrivacyRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_roles(UserRole.STUDENT.value)),
        Depends(verify_authenticated_csrf),
    ],
)
async def submit_privacy_request(
    request: Request,
    payload: PrivacyRequestCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> PrivacyRequestResponse:
    try:
        return await create_privacy_request(
            db,
            user_id=principal.user.id,
            institution_id=principal.institution_id,
            payload=payload,
            correlation_id=request.state.correlation_id,
        )
    except PrivacyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@tnp_router.get("/requests", response_model=list[PrivacyRequestResponse])
async def read_institution_requests(
    db: Database, principal: CurrentPrincipal
) -> list[PrivacyRequestResponse]:
    if principal.institution_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Institution required")
    return await list_institution_privacy_requests(db, institution_id=principal.institution_id)


@tnp_router.patch(
    "/requests/{request_id}",
    response_model=PrivacyRequestResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_institution_request(
    request_id: UUID,
    request: Request,
    payload: PrivacyRequestDecision,
    db: Database,
    principal: CurrentPrincipal,
) -> PrivacyRequestResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Institution required")
    try:
        return await decide_privacy_request(
            db,
            request_id=request_id,
            institution_id=principal.institution_id,
            actor_user_id=principal.user.id,
            payload=payload,
            correlation_id=request.state.correlation_id,
            max_cleanup_attempts=get_settings().privacy_cleanup_max_attempts,
        )
    except PrivacyError as error:
        code = str(error)
        http_status = (
            status.HTTP_404_NOT_FOUND if code.endswith("_not_found") else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=http_status, detail=code) from error


@tnp_router.get("/legal-holds", response_model=list[LegalHoldResponse])
async def read_legal_holds(
    db: Database, principal: CurrentPrincipal
) -> list[LegalHoldResponse]:
    if principal.institution_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Institution required")
    return await list_legal_holds(db, institution_id=principal.institution_id)


@tnp_router.post(
    "/legal-holds",
    response_model=LegalHoldResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def add_legal_hold(
    request: Request,
    payload: LegalHoldCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> LegalHoldResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Institution required")
    try:
        return await create_legal_hold(
            db,
            institution_id=principal.institution_id,
            actor_user_id=principal.user.id,
            payload=payload,
            correlation_id=request.state.correlation_id,
        )
    except PrivacyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@tnp_router.patch(
    "/legal-holds/{hold_id}/release",
    response_model=LegalHoldResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def remove_legal_hold(
    hold_id: UUID,
    request: Request,
    payload: LegalHoldRelease,
    db: Database,
    principal: CurrentPrincipal,
) -> LegalHoldResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Institution required")
    try:
        return await release_legal_hold(
            db,
            institution_id=principal.institution_id,
            hold_id=hold_id,
            actor_user_id=principal.user.id,
            payload=payload,
            correlation_id=request.state.correlation_id,
        )
    except PrivacyError as error:
        code = str(error)
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if code.endswith("_not_found")
                else status.HTTP_409_CONFLICT
            ),
            detail=code,
        ) from error


@router.post(
    "/deletion-requests",
    response_model=DataDeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_roles(UserRole.STUDENT.value)),
        Depends(verify_authenticated_csrf),
    ],
)
async def create_deletion_request(
    request: Request,
    payload: DataDeletionCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> DataDeletionResponse:
    try:
        return await request_student_deletion(
            db,
            user_id=principal.user.id,
            institution_id=principal.institution_id,
            correlation_id=request.state.correlation_id,
            account_wide=payload.scope == "account_all_memberships",
            max_cleanup_attempts=get_settings().privacy_cleanup_max_attempts,
        )
    except PrivacyError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
