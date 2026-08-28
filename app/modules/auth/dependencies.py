import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.models.auth import (
    ADMIN_ROLE_VALUES,
    InstitutionMembership,
    MembershipStatus,
    Session,
    User,
)
from app.modules.auth.security import hash_secret

Database = Annotated[AsyncSession, Depends(get_db)]

ADMIN_ROLES = ADMIN_ROLE_VALUES
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "tnp_owner": frozenset(
        {
            "institution.manage",
            "recruitment.read",
            "recruitment.manage",
            "applications.review",
            "intelligence.review",
            "operations.read",
            "operations.manage",
            "audit.read",
            "audit.export",
        }
    ),
    "tnp_admin": frozenset(
        {
            "institution.manage",
            "recruitment.read",
            "recruitment.manage",
            "applications.review",
            "intelligence.review",
            "operations.read",
            "operations.manage",
            "audit.read",
            "audit.export",
        }
    ),
    "tnp_reviewer": frozenset(
        {
            "recruitment.read",
            "applications.review",
            "intelligence.review",
            "operations.read",
        }
    ),
    "tnp_auditor": frozenset({"recruitment.read", "operations.read", "audit.read", "audit.export"}),
}


def _is_expired(value: datetime) -> bool:
    expires_at = value if value.tzinfo else value.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def verify_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    allowed = {str(item).rstrip("/") for item in get_settings().frontend_origins}
    if origin not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Request origin is not allowed"
        )


def verify_public_csrf(request: Request) -> None:
    verify_origin(request)
    settings = get_settings()
    cookie = request.cookies.get(settings.csrf_cookie_name, "")
    header = request.headers.get("X-CSRF-Token", "")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


async def get_current_session(
    db: Database,
    session_token: Annotated[str | None, Cookie(alias=get_settings().session_cookie_name)] = None,
) -> Session:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    session = await db.scalar(
        select(Session)
        .options(selectinload(Session.user), selectinload(Session.active_membership))
        .where(Session.token_hash == hash_secret(session_token), Session.revoked_at.is_(None))
    )
    if session is None or _is_expired(session.expires_at) or not session.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return session


CurrentSession = Annotated[Session, Depends(get_current_session)]


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user: User
    session: Session
    membership: InstitutionMembership | None

    @property
    def role(self) -> str:
        if self.membership is not None:
            return self.membership.role
        return self.user.role

    @property
    def institution_id(self) -> UUID | None:
        if self.membership is not None:
            return self.membership.institution_id
        return self.user.institution_id


@dataclass(frozen=True)
class TenantContext:
    """Server-derived tenant identity passed into tenant-owned workflows.

    The browser must never select an institution for an authorization decision.
    Route handlers obtain this object from the authenticated session and pass its
    values into domain services and audit records.
    """

    institution_id: UUID
    user_id: UUID
    role: str


async def get_current_principal(session: CurrentSession) -> AuthenticatedPrincipal:
    membership = session.active_membership
    if membership is not None and membership.status != MembershipStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": f"membership_{membership.status}",
                "message": "Institution access is restricted. Contact your placement office.",
            },
        )
    effective_role = membership.role if membership is not None else session.user.role
    if effective_role in ADMIN_ROLES and session.mfa_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "mfa_required",
                "message": "Complete administrator verification to continue.",
            },
        )
    return AuthenticatedPrincipal(user=session.user, session=session, membership=membership)


CurrentPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_current_principal)]


async def get_tenant_context(principal: CurrentPrincipal) -> TenantContext:
    if principal.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active institution membership is required",
        )
    return TenantContext(
        institution_id=principal.institution_id,
        user_id=principal.user.id,
        role=principal.role,
    )


CurrentTenant = Annotated[TenantContext, Depends(get_tenant_context)]


def verify_authenticated_csrf(request: Request, session: CurrentSession) -> None:
    verify_origin(request)
    settings = get_settings()
    cookie = request.cookies.get(settings.csrf_cookie_name, "")
    header = request.headers.get("X-CSRF-Token", "")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    if not secrets.compare_digest(hash_secret(header), session.csrf_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")


async def get_current_user(session: CurrentSession) -> User:
    return session.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str):  # type: ignore[no-untyped-def]
    async def check_role(principal: CurrentPrincipal) -> AuthenticatedPrincipal:
        if principal.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return principal

    return check_role


def require_permissions(*permissions: str):  # type: ignore[no-untyped-def]
    required = frozenset(permissions)

    async def check_permissions(principal: CurrentPrincipal) -> AuthenticatedPrincipal:
        granted = ROLE_PERMISSIONS.get(principal.role, frozenset())
        if not required.issubset(granted):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "permission_denied",
                    "message": "This administrator role cannot perform that action.",
                },
            )
        return principal

    return check_permissions


def require_recent_reauthentication(principal: CurrentPrincipal) -> None:
    verified_at = principal.session.mfa_verified_at
    if verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "reauthentication_required", "message": "Verify MFA again."},
        )
    normalized = verified_at if verified_at.tzinfo else verified_at.replace(tzinfo=UTC)
    if (datetime.now(UTC) - normalized).total_seconds() > 10 * 60:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "reauthentication_required",
                "message": "Verify MFA again before this sensitive action.",
            },
        )


def require_institution(
    principal: CurrentPrincipal, institution_id: UUID
) -> AuthenticatedPrincipal:
    if principal.institution_id is None or principal.institution_id != institution_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Resource is outside the active institution",
        )
    return principal
