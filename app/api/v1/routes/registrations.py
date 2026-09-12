import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rate_limit import enforce_auth_identity_rate_limit, enforce_auth_rate_limit
from app.models.auth import InstitutionRegistrationRequest, RegistrationStatus
from app.modules.auth.dependencies import Database, verify_public_csrf
from app.modules.auth.registration import (
    RegistrationConflictError,
    RegistrationTokenError,
    decide_institution_registration,
    start_institution_registration,
    verify_institution_registration,
)
from app.modules.auth.schemas import (
    InstitutionRegistrationDecision,
    InstitutionRegistrationRequestCreate,
    InstitutionRegistrationResponse,
    InstitutionRegistrationStartResponse,
    RegistrationTokenRequest,
)

public_router = APIRouter(prefix="/auth/institution-registrations")
operator_router = APIRouter(prefix="/operator/institution-registration-requests")


def _verify_operator_key(value: str | None) -> None:
    configured = get_settings().operator_bootstrap_key
    if configured is None or value is None or not secrets.compare_digest(configured, value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator access denied")


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


@operator_router.get("", response_model=list[InstitutionRegistrationResponse])
async def list_registration_requests(
    db: Database,
    x_operator_key: Annotated[str | None, Header()] = None,
) -> list[InstitutionRegistrationResponse]:
    _verify_operator_key(x_operator_key)
    records = await db.scalars(
        select(InstitutionRegistrationRequest)
        .where(
            InstitutionRegistrationRequest.status.in_(
                (
                    RegistrationStatus.PENDING_APPROVAL.value,
                    RegistrationStatus.DUPLICATE_REVIEW.value,
                )
            )
        )
        .order_by(InstitutionRegistrationRequest.created_at)
        .limit(100)
    )
    return [InstitutionRegistrationResponse.model_validate(item) for item in records.all()]


@operator_router.post("/{request_id}/decision", response_model=InstitutionRegistrationResponse)
async def review_registration_request(
    request_id: UUID,
    payload: InstitutionRegistrationDecision,
    request: Request,
    db: Database,
    x_operator_key: Annotated[str | None, Header()] = None,
) -> InstitutionRegistrationResponse:
    _verify_operator_key(x_operator_key)
    try:
        item = await decide_institution_registration(
            db,
            request_id=request_id,
            approve=payload.decision == "approve",
            reason=payload.reason,
            correlation_id=request.state.correlation_id,
        )
    except RegistrationConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": str(error), "message": "The request cannot be processed."},
        ) from None
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return InstitutionRegistrationResponse.model_validate(item)
