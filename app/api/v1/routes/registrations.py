from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.rate_limit import enforce_auth_identity_rate_limit, enforce_auth_rate_limit
from app.modules.auth.dependencies import Database, verify_public_csrf
from app.modules.auth.registration import (
    RegistrationConflictError,
    RegistrationTokenError,
    start_institution_registration,
    verify_institution_registration,
)
from app.modules.auth.schemas import (
    InstitutionRegistrationRequestCreate,
    InstitutionRegistrationResponse,
    InstitutionRegistrationStartResponse,
    RegistrationTokenRequest,
)

public_router = APIRouter(prefix="/auth/institution-registrations")


@public_router.post(
    "", response_model=InstitutionRegistrationStartResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_registration_request(
    payload: InstitutionRegistrationRequestCreate,
    request: Request,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> InstitutionRegistrationStartResponse:
    await enforce_auth_identity_rate_limit(request, str(payload.institutional_email))
    try:
        item = await start_institution_registration(
            db,
            institution_name=payload.institution_name,
            institution_code=payload.institution_code,
            domain=payload.domain,
            admin_email=str(payload.institutional_email),
            correlation_id=request.state.correlation_id,
        )
    except RegistrationConflictError as error:
        code = str(error)
        message = (
            "Use an email address controlled by the institution domain."
            if code == "institutional_email_required"
            else "A registration request already exists for this administrator."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": code, "message": message},
        ) from None
    return InstitutionRegistrationStartResponse(
        request_id=item.id,
        status="verification_pending",
        message="Check the institutional inbox to verify this registration request.",
    )


@public_router.post("/verify", response_model=InstitutionRegistrationResponse)
async def verify_registration_request(
    payload: RegistrationTokenRequest,
    request: Request,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> InstitutionRegistrationResponse:
    try:
        item = await verify_institution_registration(
            db, raw_token=payload.token, correlation_id=request.state.correlation_id
        )
    except RegistrationTokenError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "registration_token_invalid",
                "message": "This verification link is invalid or expired.",
            },
        ) from None
    return InstitutionRegistrationResponse.model_validate(item)
