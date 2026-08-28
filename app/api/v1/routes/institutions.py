import secrets
from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import PlainTextResponse

from app.core.config import get_settings
from app.models.auth import RosterImport, RosterImportRow, UserRole
from app.modules.auth.dependencies import (
    AuthenticatedPrincipal,
    Database,
    require_institution,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.institutions.lifecycle import (
    InvalidRosterError,
    ProvisionConflictError,
    commit_roster,
    get_roster_import,
    preview_roster,
    provision_institution,
    resend_invitation,
)
from app.modules.institutions.schemas import (
    InstitutionProvisionRequest,
    InstitutionProvisionResponse,
    MembershipCreate,
    MembershipResponse,
    MembershipStatusUpdate,
    RosterImportResponse,
    RosterRowResponse,
)
from app.modules.institutions.service import (
    MembershipUserNotFoundError,
    list_memberships,
    update_membership_status,
    verify_membership,
)

router = APIRouter(prefix="/institutions/{institution_id}")
operator_router = APIRouter(prefix="/operator")
InstitutionAdmin = Annotated[
    AuthenticatedPrincipal, Depends(require_roles(UserRole.TNP_ADMIN.value))
]


@router.get("/memberships", response_model=list[MembershipResponse])
async def read_memberships(
    institution_id: UUID, db: Database, principal: InstitutionAdmin
) -> list[MembershipResponse]:
    require_institution(principal, institution_id)
    return [
        MembershipResponse.model_validate(item).model_copy(update={"email": item.user.email})
        for item in await list_memberships(db, institution_id)
    ]


@router.post(
    "/memberships",
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


@router.patch(
    "/memberships/{membership_id}",
    response_model=MembershipResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def change_membership_status(
    institution_id: UUID,
    membership_id: UUID,
    payload: MembershipStatusUpdate,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
) -> MembershipResponse:
    require_institution(principal, institution_id)
    membership = await update_membership_status(
        db,
        institution_id=institution_id,
        membership_id=membership_id,
        status=payload.status,
        reason=payload.reason,
        actor_user_id=principal.user.id,
        correlation_id=request.state.correlation_id,
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership was not found"
        )
    return MembershipResponse.model_validate(membership)


def _roster_response(
    roster: RosterImport,
    rows: Sequence[RosterImportRow],
    tokens: dict[UUID, str] | None = None,
) -> RosterImportResponse:
    token_map = tokens or {}
    return RosterImportResponse(
        id=roster.id,
        status=roster.status,
        total_rows=roster.total_rows,
        valid_rows=roster.valid_rows,
        invalid_rows=roster.invalid_rows,
        invited_rows=roster.invited_rows,
        committed_at=roster.committed_at,
        rows=[
            RosterRowResponse(
                row_number=row.row_number,
                email=row.email,
                enrollment_id=row.enrollment_id,
                full_name=row.full_name,
                status=row.status,
                errors=row.errors,
                activation_token=token_map.get(row.id),
            )
            for row in rows
        ],
    )


@router.get("/roster-imports/template", response_class=PlainTextResponse)
async def roster_template(institution_id: UUID, principal: InstitutionAdmin) -> PlainTextResponse:
    require_institution(principal, institution_id)
    return PlainTextResponse(
        "email,enrollment_id,full_name\nstudent@example.edu,ENR-001,Student Name\n",
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="campushire-roster-template.csv"'},
    )


@router.post(
    "/roster-imports/preview",
    response_model=RosterImportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def preview_roster_import(
    institution_id: UUID,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
    file: Annotated[UploadFile, File()],
) -> RosterImportResponse:
    require_institution(principal, institution_id)
    try:
        roster = await preview_roster(
            db,
            institution_id=institution_id,
            actor_user_id=principal.user.id,
            filename=file.filename or "roster.csv",
            content=await file.read(get_settings().roster_max_bytes + 1),
            correlation_id=request.state.correlation_id,
        )
    except InvalidRosterError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_roster", "message": str(error)},
        ) from error
    _, rows = await get_roster_import(db, institution_id, roster.id)
    return _roster_response(roster, rows)


@router.get("/roster-imports/{roster_import_id}", response_model=RosterImportResponse)
async def read_roster_import(
    institution_id: UUID,
    roster_import_id: UUID,
    db: Database,
    principal: InstitutionAdmin,
) -> RosterImportResponse:
    require_institution(principal, institution_id)
    roster, rows = await get_roster_import(db, institution_id, roster_import_id)
    if roster is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roster import was not found"
        )
    return _roster_response(roster, rows)


@router.post(
    "/roster-imports/{roster_import_id}/commit",
    response_model=RosterImportResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def commit_roster_import(
    institution_id: UUID,
    roster_import_id: UUID,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
) -> RosterImportResponse:
    require_institution(principal, institution_id)
    roster, tokens = await commit_roster(
        db,
        institution_id=institution_id,
        roster_import_id=roster_import_id,
        actor_user_id=principal.user.id,
        correlation_id=request.state.correlation_id,
    )
    if roster is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Roster import was not found"
        )
    _, rows = await get_roster_import(db, institution_id, roster.id)
    return _roster_response(roster, rows, tokens)


@router.post(
    "/invitations/{invitation_id}/resend",
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def resend_membership_invitation(
    institution_id: UUID,
    invitation_id: UUID,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
) -> dict[str, str]:
    require_institution(principal, institution_id)
    invitation, token = await resend_invitation(
        db,
        institution_id=institution_id,
        invitation_id=invitation_id,
        actor_user_id=principal.user.id,
        correlation_id=request.state.correlation_id,
    )
    if invitation is None or token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invitation was not found"
        )
    return {"activation_token": token, "expires_at": invitation.expires_at.isoformat()}


@operator_router.post(
    "/institutions",
    response_model=InstitutionProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_institution(
    payload: InstitutionProvisionRequest,
    request: Request,
    db: Database,
    x_operator_key: Annotated[str | None, Header()] = None,
) -> InstitutionProvisionResponse:
    configured = get_settings().operator_bootstrap_key
    if (
        configured is None
        or x_operator_key is None
        or not secrets.compare_digest(configured, x_operator_key)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator access denied")
    try:
        result = await provision_institution(
            db,
            code=payload.institution_code,
            name=payload.institution_name,
            admin_email=str(payload.admin_email),
            correlation_id=request.state.correlation_id,
        )
    except ProvisionConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "institution_conflict",
                "message": "Institution provisioning conflicts with an existing record.",
            },
        ) from None
    return InstitutionProvisionResponse(
        institution_id=result.institution.id,
        admin_invitation_id=result.invitation.id,
        admin_invitation_token=result.raw_token,
        expires_at=result.invitation.expires_at,
    )
