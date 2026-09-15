from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.onboarding.schemas import (
    InstitutionOnboardingResponse,
    InstitutionOnboardingUpdate,
    StudentOnboardingResponse,
    StudentOnboardingUpdate,
)
from app.modules.onboarding.service import (
    OnboardingConflictError,
    OnboardingValidationError,
    get_institution_onboarding,
    get_student_onboarding,
    update_institution_onboarding,
    update_student_onboarding,
)

student_router = APIRouter(
    prefix="/onboarding", dependencies=[Depends(require_roles(UserRole.STUDENT.value))]
)
admin_router = APIRouter(
    prefix="/onboarding",
    dependencies=[Depends(require_roles(UserRole.TNP_OWNER.value))],
)


def _raise_onboarding_error(error: Exception) -> NoReturn:
    if isinstance(error, OnboardingConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "onboarding_revision_conflict",
                "message": "Onboarding changed in another session.",
                "current_revision": error.current_revision,
            },
        ) from error
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "onboarding_invalid", "message": str(error)},
    ) from error


@student_router.get("", response_model=StudentOnboardingResponse)
async def read_student_onboarding(
    db: Database, principal: CurrentPrincipal
) -> StudentOnboardingResponse:
    return await get_student_onboarding(db, principal.user, principal.institution_id)


@student_router.put(
    "/step",
    response_model=StudentOnboardingResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def save_student_onboarding_step(
    payload: StudentOnboardingUpdate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> StudentOnboardingResponse:
    try:
        return await update_student_onboarding(
            db,
            user=principal.user,
            institution_id=principal.institution_id,
            payload=payload,
            correlation_id=request.state.correlation_id,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        _raise_onboarding_error(error)


@admin_router.get("", response_model=InstitutionOnboardingResponse)
async def read_institution_onboarding(
    db: Database, principal: CurrentPrincipal
) -> InstitutionOnboardingResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution membership required")
    try:
        return await get_institution_onboarding(db, principal.institution_id)
    except OnboardingValidationError as error:
        _raise_onboarding_error(error)


@admin_router.put(
    "/step",
    response_model=InstitutionOnboardingResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def save_institution_onboarding_step(
    payload: InstitutionOnboardingUpdate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> InstitutionOnboardingResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution membership required")
    try:
        return await update_institution_onboarding(
            db,
            institution_id=principal.institution_id,
            actor_user_id=principal.user.id,
            payload=payload,
            correlation_id=request.state.correlation_id,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        _raise_onboarding_error(error)
