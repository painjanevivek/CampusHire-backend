from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import get_settings
from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.privacy.schemas import DataDeletionCreate, DataDeletionResponse
from app.modules.privacy.service import PrivacyError, request_student_deletion

router = APIRouter(prefix="/privacy")


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
