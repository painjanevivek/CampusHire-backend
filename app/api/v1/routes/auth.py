from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.core.config import get_settings
from app.core.rate_limit import enforce_auth_identity_rate_limit, enforce_auth_rate_limit
from app.models.auth import ADMIN_ROLE_VALUES, InstitutionMembership, User
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentSession,
    Database,
    verify_authenticated_csrf,
    verify_public_csrf,
)
from app.modules.auth.schemas import (
    InvitationAcceptRequest,
    InvitationResponse,
    MfaCodeRequest,
    MfaConfirmResponse,
    MfaSetupResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionResponse,
    SignInRequest,
    SignInResponse,
    SignupRequest,
    UserResponse,
)
from app.modules.auth.service import (
    ExpiredOrUsedTokenError,
    InvalidCredentialsError,
    InvalidMfaCodeError,
    MfaReauthenticationRequiredError,
    accept_invitation,
    authenticate,
    begin_mfa_setup,
    confirm_mfa_setup,
    confirm_password_reset,
    get_invitation,
    issue_password_reset,
    list_sessions,
    revoke_all_sessions,
    revoke_session,
    revoke_session_by_id,
    rotate_session_csrf,
    verify_mfa,
)

router = APIRouter(prefix="/auth")


def _set_csrf_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        secure=not settings.is_development,
        httponly=False,
        samesite="strict",
        path="/",
        max_age=settings.session_ttl_hours * 3600,
    )


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.session_cookie_name,
        token,
        secure=not settings.is_development,
        httponly=True,
        samesite="strict",
        path="/",
        max_age=settings.session_ttl_hours * 3600,
    )
    _set_csrf_cookie(response, csrf_token)


def _user_response(user: User, membership: InstitutionMembership | None = None) -> UserResponse:
    response = UserResponse.model_validate(user)
    if membership is None:
        return response
    return response.model_copy(
        update={
            "role": membership.role,
            "institution_id": membership.institution_id,
            "membership_id": membership.id,
            "membership_status": membership.status,
        }
    )


@router.get("/csrf", status_code=status.HTTP_204_NO_CONTENT)
async def csrf(request: Request, response: Response, db: Database) -> None:
    settings = get_settings()
    token = await rotate_session_csrf(db, request.cookies.get(settings.session_cookie_name))
    _set_csrf_cookie(response, token)


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> UserResponse:
    del payload, request, response, db
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "invitation_required",
            "message": "CampusHire accounts are activated from an institution invitation.",
        },
    )


@router.post("/sign-in", response_model=SignInResponse)
async def sign_in(
    payload: SignInRequest,
    request: Request,
    response: Response,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> SignInResponse:
    await enforce_auth_identity_rate_limit(request, str(payload.email))
    try:
        auth_session = await authenticate(
            db,
            str(payload.email),
            payload.password,
            get_settings().session_ttl_hours,
            request.headers.get("User-Agent"),
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Invalid email or password"},
        ) from None
    _set_session_cookies(response, auth_session.token, auth_session.csrf_token)
    return SignInResponse(
        user=_user_response(auth_session.user, auth_session.membership),
        next_step=auth_session.next_step,
    )


@router.get("/invitations/{token}", response_model=InvitationResponse)
async def validate_invitation(token: str, db: Database) -> InvitationResponse:
    try:
        invitation = await get_invitation(db, token)
    except ExpiredOrUsedTokenError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "invitation_unavailable",
                "message": "This invitation is no longer available.",
            },
        ) from None
    return InvitationResponse.model_validate(invitation, from_attributes=True)


@router.post(
    "/invitations/{token}/accept",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def activate_invitation(
    token: str,
    payload: InvitationAcceptRequest,
    request: Request,
    response: Response,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> UserResponse:
    try:
        user = await accept_invitation(
            db,
            raw_token=token,
            password=payload.password,
            terms_version=payload.terms_version,
            privacy_version=payload.privacy_version,
            correlation_id=request.state.correlation_id,
        )
    except ExpiredOrUsedTokenError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "invitation_unavailable",
                "message": "This invitation is no longer available.",
            },
        ) from None
    auth_session = await authenticate(
        db,
        user.email,
        payload.password,
        get_settings().session_ttl_hours,
        request.headers.get("User-Agent"),
    )
    _set_session_cookies(response, auth_session.token, auth_session.csrf_token)
    return _user_response(auth_session.user, auth_session.membership)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> dict[str, str]:
    await enforce_auth_identity_rate_limit(request, str(payload.email))
    await issue_password_reset(db, str(payload.email), request.state.correlation_id)
    return {"message": "If the account exists, password reset instructions will be sent."}


@router.post(
    "/password-reset/{token}/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def reset_password(
    token: str,
    payload: PasswordResetConfirm,
    request: Request,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> None:
    try:
        await confirm_password_reset(db, token, payload.password, request.state.correlation_id)
    except ExpiredOrUsedTokenError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "reset_unavailable",
                "message": "This reset link is no longer available.",
            },
        ) from None


def _require_admin_session(session: CurrentSession) -> None:
    if (
        session.active_membership is not None
        and session.active_membership.status != "active"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "membership_inactive", "message": "Membership is inactive."},
        )
    role = (
        session.active_membership.role
        if session.active_membership is not None
        else session.user.role
    )
    if role not in ADMIN_ROLE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required"
        )


@router.post(
    "/mfa/setup", response_model=MfaSetupResponse, dependencies=[Depends(verify_authenticated_csrf)]
)
async def setup_mfa(db: Database, session: CurrentSession) -> MfaSetupResponse:
    _require_admin_session(session)
    try:
        secret = await begin_mfa_setup(db, session)
    except MfaReauthenticationRequiredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "mfa_reauthentication_required",
                "message": "Verify the enrolled factor before replacing it.",
            },
        ) from None
    label = quote(session.user.email)
    uri = f"otpauth://totp/CampusHire:{label}?secret={secret}&issuer=CampusHire&digits=6&period=30"
    return MfaSetupResponse(secret=secret, provisioning_uri=uri)


@router.post(
    "/mfa/confirm",
    response_model=MfaConfirmResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def confirm_mfa(
    payload: MfaCodeRequest, db: Database, session: CurrentSession
) -> MfaConfirmResponse:
    _require_admin_session(session)
    try:
        codes = await confirm_mfa_setup(db, session, payload.code)
    except MfaReauthenticationRequiredError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "mfa_reauthentication_required",
                "message": "Verify the enrolled factor before replacing it.",
            },
        ) from None
    except InvalidMfaCodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_mfa_code", "message": "The verification code is invalid."},
        ) from None
    return MfaConfirmResponse(recovery_codes=codes)


@router.post(
    "/mfa/challenge",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def challenge_mfa(payload: MfaCodeRequest, db: Database, session: CurrentSession) -> None:
    _require_admin_session(session)
    try:
        await verify_mfa(db, session, payload.code)
    except InvalidMfaCodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_mfa_code", "message": "The verification code is invalid."},
        ) from None


@router.get("/sessions", response_model=list[SessionResponse])
async def read_sessions(db: Database, principal: CurrentPrincipal) -> list[SessionResponse]:
    records = await list_sessions(db, principal.user.id)
    return [
        SessionResponse(
            id=item.id,
            created_at=item.created_at,
            last_activity_at=item.last_activity_at,
            expires_at=item.expires_at,
            device_summary=item.device_summary,
            current=item.id == principal.session.id,
        )
        for item in records
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def delete_session(session_id: UUID, db: Database, principal: CurrentPrincipal) -> None:
    if not await revoke_session_by_id(db, user_id=principal.user.id, session_id=session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session was not found")


@router.get("/me", response_model=UserResponse)
async def me(principal: CurrentPrincipal) -> UserResponse:
    return _user_response(principal.user, principal.membership)


@router.post(
    "/sign-out",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def sign_out(response: Response, db: Database, session: CurrentSession) -> None:
    await revoke_session(db, session)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.post(
    "/sign-out-all",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def sign_out_all(response: Response, db: Database, principal: CurrentPrincipal) -> None:
    await revoke_all_sessions(db, principal.user, principal.institution_id)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
