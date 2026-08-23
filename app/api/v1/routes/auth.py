from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.rate_limit import enforce_auth_rate_limit
from app.models.auth import InstitutionMembership, User
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentSession,
    Database,
    verify_authenticated_csrf,
    verify_public_csrf,
)
from app.modules.auth.schemas import SignInRequest, SignupRequest, UserResponse
from app.modules.auth.service import (
    DuplicateEmailError,
    InvalidCredentialsError,
    authenticate,
    create_student,
    revoke_all_sessions,
    revoke_session,
    rotate_session_csrf,
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


def _user_response(
    user: User, membership: InstitutionMembership | None = None
) -> UserResponse:
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
    token = await rotate_session_csrf(
        db, request.cookies.get(settings.session_cookie_name)
    )
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
    try:
        user = await create_student(db, str(payload.email), payload.password)
    except DuplicateEmailError:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "An account with this email already exists"},
        )  # type: ignore[return-value]
    auth_session = await authenticate(
        db,
        user.email,
        payload.password,
        get_settings().session_ttl_hours,
        request.headers.get("User-Agent"),
    )
    _set_session_cookies(response, auth_session.token, auth_session.csrf_token)
    return _user_response(auth_session.user, auth_session.membership)


@router.post("/sign-in", response_model=UserResponse)
async def sign_in(
    payload: SignInRequest,
    request: Request,
    response: Response,
    db: Database,
    _: Annotated[None, Depends(verify_public_csrf)],
    __: Annotated[None, Depends(enforce_auth_rate_limit)],
) -> UserResponse:
    try:
        auth_session = await authenticate(
            db,
            str(payload.email),
            payload.password,
            get_settings().session_ttl_hours,
            request.headers.get("User-Agent"),
        )
    except InvalidCredentialsError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid email or password"},
        )  # type: ignore[return-value]
    _set_session_cookies(response, auth_session.token, auth_session.csrf_token)
    return _user_response(auth_session.user, auth_session.membership)


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
async def sign_out_all(
    response: Response, db: Database, principal: CurrentPrincipal
) -> None:
    await revoke_all_sessions(db, principal.user, principal.institution_id)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
