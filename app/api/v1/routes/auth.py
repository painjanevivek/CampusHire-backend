from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rate_limit import enforce_auth_identity_rate_limit, enforce_auth_rate_limit
from app.models.auth import (
    ADMIN_ROLE_VALUES,
    TNP_ROLE_VALUES,
    Institution,
    InstitutionMembership,
    MembershipStatus,
    User,
    UserRole,
)
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentSession,
    Database,
    permissions_for_role,
    verify_authenticated_csrf,
    verify_public_csrf,
    workspace_for_role,
)
from app.modules.auth.registration import start_student_registration
from app.modules.auth.schemas import (
    ActiveMembershipRequest,
    DemoSignInRequest,
    InvitationAcceptRequest,
    InvitationResponse,
    MembershipChoice,
    MfaCodeRequest,
    MfaConfirmResponse,
    MfaDisableRequest,
    MfaSetupResponse,
    MfaStatusResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegistrationStartResponse,
    SessionResponse,
    SignInRequest,
    SignInResponse,
    SignupRequest,
    TermsAcceptanceRequest,
    UserResponse,
)
from app.modules.auth.service import (
    ExpiredOrUsedTokenError,
    InvalidCredentialsError,
    InvalidMfaCodeError,
    MfaReauthenticationRequiredError,
    accept_invitation,
    accept_staff_terms,
    authenticate,
    begin_mfa_setup,
    confirm_mfa_setup,
    confirm_password_reset,
    disable_mfa,
    get_invitation,
    has_prepared_student_registration,
    is_mfa_enabled,
    issue_password_reset,
    list_sessions,
    revoke_all_sessions,
    revoke_session,
    revoke_session_by_id,
    rotate_session_csrf,
    verify_mfa,
)
from app.modules.communications.service import email_delivery_configured

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
    role = membership.role if membership is not None else user.role
    response = UserResponse.model_validate(user).model_copy(
        update={
            "workspace": workspace_for_role(role),
            "capabilities": sorted(permissions_for_role(role)),
        }
    )
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


@router.post(
    "/signup", response_model=RegistrationStartResponse, status_code=status.HTTP_201_CREATED
)
async def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> RegistrationStartResponse:
    await enforce_auth_identity_rate_limit(request, str(payload.email))
    result = await start_student_registration(
        db,
        name=payload.name,
        surname=payload.surname,
        dob=payload.dob,
        email=str(payload.email),
        password=payload.password,
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
        invitation_code=payload.invitation_code,
        correlation_id=request.state.correlation_id,
    )
    if result.status == "registration_unavailable":
        response.status_code = status.HTTP_409_CONFLICT
        return RegistrationStartResponse(
            status=result.status,
            message=(
                "We could not verify this college email for sign-up. Use an email on your "
                "college's verified domain. If you have a code, use the invited email address; "
                "otherwise, contact your placement office."
            ),
        )
    if result.status == "approval_pending":
        response.status_code = status.HTTP_202_ACCEPTED
        return RegistrationStartResponse(
            status=result.status,
            message=(
                "Your request was recorded for placement-office review. Your account is not "
                "active yet. Ask your office to verify your identity and provide a one-time "
                "invitation code."
            ),
        )
    auth_session = await authenticate(
        db,
        str(payload.email),
        payload.password,
        get_settings().session_ttl_hours,
        request.headers.get("User-Agent"),
        required_role=UserRole.STUDENT.value,
    )
    _set_session_cookies(response, auth_session.token, auth_session.csrf_token)
    return RegistrationStartResponse(
        status=result.status,
        next_path=result.next_path,
        message="Account created. Continue to your student profile.",
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
    await enforce_auth_identity_rate_limit(request, payload.identifier)
    workspace_roles = {
        "student": frozenset({UserRole.STUDENT.value}),
        "tnp": frozenset(
            {
                UserRole.TNP_OWNER.value,
                UserRole.TNP_ADMIN.value,
                UserRole.TNP_REVIEWER.value,
                UserRole.TNP_AUDITOR.value,
            }
        ),
        "admin": frozenset({UserRole.PLATFORM_ADMIN.value}),
    }
    try:
        auth_session = await authenticate(
            db,
            payload.identifier,
            payload.password,
            get_settings().session_ttl_hours,
            request.headers.get("User-Agent"),
            required_roles=workspace_roles.get(payload.workspace) if payload.workspace else None,
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "invalid_credentials",
                "message": "Invalid username, email, or password",
            },
        ) from None
    _set_session_cookies(response, auth_session.token, auth_session.csrf_token)
    return SignInResponse(
        user=_user_response(auth_session.user, auth_session.membership),
        next_step=auth_session.next_step,
    )


def _require_tnp_context_session(session: CurrentSession) -> None:
    if session.user.role not in TNP_ROLE_VALUES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="T&P access required")
    if session.user.requires_terms_acceptance or session.mfa_verified_at is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Complete sign-in first")


@router.get("/memberships", response_model=list[MembershipChoice])
async def read_active_memberships(
    db: Database, session: CurrentSession
) -> list[MembershipChoice]:
    _require_tnp_context_session(session)
    rows = (
        await db.execute(
            select(InstitutionMembership, Institution.name)
            .join(Institution, Institution.id == InstitutionMembership.institution_id)
            .where(
                InstitutionMembership.user_id == session.user_id,
                InstitutionMembership.status == MembershipStatus.ACTIVE.value,
                InstitutionMembership.role.in_(TNP_ROLE_VALUES),
                Institution.is_active.is_(True),
            )
            .order_by(Institution.name, InstitutionMembership.id)
        )
    ).all()
    return [
        MembershipChoice(
            id=membership.id,
            institution_id=membership.institution_id,
            institution_name=name,
            role=membership.role,
        )
        for membership, name in rows
    ]


@router.post(
    "/active-membership",
    response_model=UserResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def select_active_membership(
    payload: ActiveMembershipRequest,
    request: Request,
    db: Database,
    session: CurrentSession,
) -> UserResponse:
    _require_tnp_context_session(session)
    membership = await db.scalar(
        select(InstitutionMembership)
        .join(Institution, Institution.id == InstitutionMembership.institution_id)
        .where(
            InstitutionMembership.id == payload.membership_id,
            InstitutionMembership.user_id == session.user_id,
            InstitutionMembership.role.in_(TNP_ROLE_VALUES),
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
            Institution.is_active.is_(True),
        )
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment unavailable")
    previous_institution_id = (
        session.active_membership.institution_id
        if session.active_membership is not None
        else None
    )
    session.active_membership = membership
    session.active_membership_id = membership.id
    record_audit_event(
        db,
        actor_user_id=session.user_id,
        institution_id=membership.institution_id,
        event_type="auth.institution_context_changed",
        resource_type="session",
        resource_id=str(session.id),
        correlation_id=request.state.correlation_id,
        details={"previous_institution_id": str(previous_institution_id)},
    )
    await db.commit()
    return _user_response(session.user, membership)


@router.post(
    "/terms/accept",
    response_model=SignInResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def accept_current_staff_terms(
    payload: TermsAcceptanceRequest,
    request: Request,
    db: Database,
    session: CurrentSession,
) -> SignInResponse:
    role = (
        session.active_membership.role
        if session.active_membership is not None
        else session.user.role
    )
    if role not in ADMIN_ROLE_VALUES or not session.user.requires_terms_acceptance:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "terms_acceptance_unavailable",
                "message": "This session does not require staff terms acceptance.",
            },
        )
    next_step = await accept_staff_terms(
        db,
        session=session,
        terms_version=payload.terms_version,
        privacy_version=payload.privacy_version,
        correlation_id=request.state.correlation_id,
    )
    return SignInResponse(
        user=_user_response(session.user, session.active_membership),
        next_step=next_step,
    )


@router.post("/demo-sign-in", response_model=SignInResponse)
async def demo_sign_in(
    payload: DemoSignInRequest,
    request: Request,
    response: Response,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> SignInResponse:
    settings = get_settings()
    if not settings.demo_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "demo_login_unavailable",
                "message": "Demo login is not available in this environment.",
            },
        )
    if payload.role == "student":
        identifier = settings.demo_student_email
        password = settings.demo_student_password
        required_role = UserRole.STUDENT.value
        required_roles = None
    elif payload.role == "tnp_admin":
        identifier = settings.demo_tnp_email or settings.demo_tnp_username
        password = settings.demo_tnp_password
        required_role = None
        required_roles = TNP_ROLE_VALUES
    else:
        identifier = settings.demo_admin_email
        password = settings.demo_admin_password
        required_role = UserRole.PLATFORM_ADMIN.value
        required_roles = None
    if identifier is None or password is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "demo_login_unavailable",
                "message": "The synthetic demo account is not configured.",
            },
        )
    await enforce_auth_identity_rate_limit(request, str(identifier))
    try:
        auth_session = await authenticate(
            db,
            str(identifier),
            password.get_secret_value(),
            settings.session_ttl_hours,
            request.headers.get("User-Agent"),
            required_role=required_role,
            required_roles=required_roles,
            demo_mfa_bypass=(payload.role != "student" and settings.demo_admin_mfa_bypass),
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "demo_login_unavailable",
                "message": "The synthetic demo account is not ready.",
            },
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
    return InvitationResponse(
        id=invitation.id,
        institution_id=invitation.institution_id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        student_signup_ready=await has_prepared_student_registration(db, invitation.id),
    )


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
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "password_confirmation_failed",
                "message": "Enter the password used during sign-up.",
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
    if email_delivery_configured():
        await issue_password_reset(db, str(payload.email), request.state.correlation_id)
        return {"message": "If the account exists, password reset instructions will be sent."}
    return {
        "message": (
            "CampusHire email delivery is not configured. Contact your placement office "
            "for identity-checked account recovery; no reset email was sent."
        )
    }


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
    if session.user.requires_terms_acceptance:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "terms_acceptance_required",
                "message": "Accept the current Terms and Privacy Notice before continuing.",
            },
        )
    if session.active_membership is not None and session.active_membership.status != "active":
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


@router.get("/mfa/status", response_model=MfaStatusResponse)
async def read_mfa_status(db: Database, session: CurrentSession) -> MfaStatusResponse:
    _require_admin_session(session)
    return MfaStatusResponse(enabled=await is_mfa_enabled(db, session.user_id))


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


@router.post(
    "/mfa/disable",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf), Depends(enforce_auth_rate_limit)],
)
async def reset_mfa_factor(
    payload: MfaDisableRequest,
    request: Request,
    db: Database,
    session: CurrentSession,
) -> None:
    _require_admin_session(session)
    try:
        await disable_mfa(
            db,
            session=session,
            password=payload.password,
            code=payload.code,
            correlation_id=request.state.correlation_id,
        )
    except (InvalidCredentialsError, InvalidMfaCodeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "mfa_reset_verification_failed",
                "message": "The password or verification code is invalid.",
            },
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
