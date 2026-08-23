from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    AuthenticatedPrincipal,
    Database,
    require_institution,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.institutions.schemas import MembershipCreate, MembershipResponse
from app.modules.institutions.service import (
    MembershipUserNotFoundError,
    list_memberships,
    verify_membership,
)

router = APIRouter(prefix="/institutions/{institution_id}/memberships")
InstitutionAdmin = Annotated[
    AuthenticatedPrincipal, Depends(require_roles(UserRole.TNP_ADMIN.value))
]


@router.get("", response_model=list[MembershipResponse])
async def read_memberships(
    institution_id: UUID, db: Database, principal: InstitutionAdmin
) -> list[MembershipResponse]:
    require_institution(principal, institution_id)
    return [
        MembershipResponse.model_validate(item)
        for item in await list_memberships(db, institution_id)
    ]


@router.post(
    "",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def create_membership(
    institution_id: UUID,
    payload: MembershipCreate,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
) -> MembershipResponse:
    require_institution(principal, institution_id)
    try:
        membership = await verify_membership(
            db,
            institution_id=institution_id,
            user_id=payload.user_id,
            role=payload.role.value,
            actor_user_id=principal.user.id,
            correlation_id=request.state.correlation_id,
        )
    except MembershipUserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership user was not found"
        ) from error
    return MembershipResponse.model_validate(membership)
