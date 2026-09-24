import csv
import io
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth import (
    InstitutionMembership,
    MembershipStatus,
    RegistrationStatus,
    RosterImport,
    RosterImportRow,
    StudentRegistrationRequest,
    User,
    UserRole,
)
from app.models.profile import StudentProfile
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    AuthenticatedPrincipal,
    Database,
    require_institution,
    require_permissions,
    require_recent_reauthentication,
    verify_authenticated_csrf,
)
from app.modules.auth.institutional_identity import (
    InstitutionalEmailError,
    validate_pcco_email_prn_consistency,
)
from app.modules.auth.placement_access import normalize_prn
from app.modules.auth.schemas import ManualRecoveryHandoff, ManualRecoveryRequest
from app.modules.auth.service import issue_password_reset
from app.modules.communications.service import email_delivery_configured
from app.modules.institutions.lifecycle import (
    InvalidRosterError,
    commit_roster,
    get_roster_import,
    invitation_status,
    list_invitations,
    preview_roster,
    resend_invitation,
    revoke_invitation,
)
from app.modules.institutions.schemas import (
    InvitationActionResponse,
    InvitationHandoffResponse,
    InvitationRevocationRequest,
    InvitationSummary,
    MembershipCreate,
    MembershipPage,
    MembershipResponse,
    MembershipStatusUpdate,
    RosterCommitResponse,
    RosterImportResponse,
    RosterImportSummary,
    RosterRowResponse,
    StaffAccountCreate,
    StaffAccountResponse,
    StudentAccessRequestSummary,
    StudentPrnVerificationDecision,
    StudentPrnVerificationResponse,
)
from app.modules.institutions.service import (
    MembershipPermissionError,
    MembershipUserNotFoundError,
    StaffAccountConflictError,
    create_staff_account,
    list_memberships,
    paginate_memberships,
    update_membership_status,
    verify_membership,
)

router = APIRouter(prefix="/institutions/{institution_id}")
InstitutionAdmin = Annotated[
    AuthenticatedPrincipal, Depends(require_permissions("institution.manage"))
]
InstitutionOwner = Annotated[
    AuthenticatedPrincipal, Depends(require_permissions("institution.roles.manage"))
]


@router.post(
    "/students/{student_id}/prn-verification",
    response_model=StudentPrnVerificationResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def verify_student_prn(
    institution_id: UUID,
    student_id: UUID,
    payload: StudentPrnVerificationDecision,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
) -> StudentPrnVerificationResponse:
    require_institution(principal, institution_id)
    membership = await db.scalar(
        select(InstitutionMembership.id).where(
            InstitutionMembership.institution_id == institution_id,
            InstitutionMembership.user_id == student_id,
            InstitutionMembership.role == UserRole.STUDENT.value,
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
        )
    )
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == student_id,
            StudentProfile.institution_id == institution_id,
        )
    )
    if membership is None or profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    try:
        registered_prn = normalize_prn(profile.prn) if profile.prn else None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "student_prn_requires_correction",
                "message": "Correct the student's PRN before verifying it.",
            },
        ) from error
    if registered_prn is None or registered_prn != payload.official_prn:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "student_prn_verification_mismatch",
                "message": "The entered PRN does not match the student's saved profile.",
            },
        )
    student_user = await db.get(User, student_id)
    try:
        if student_user is not None:
            validate_pcco_email_prn_consistency(student_user.email, registered_prn)
    except InstitutionalEmailError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "student_prn_email_batch_mismatch",
                "message": str(error),
            },
        ) from error
    verified_at = datetime.now(UTC)
    profile.prn_verified_at = verified_at
    profile.prn_verified_by_user_id = principal.user.id
    record_audit_event(
        db,
        actor_user_id=principal.user.id,
        institution_id=institution_id,
        event_type="student.prn_verified",
        resource_type="student_profile",
        resource_id=str(profile.id),
        reason=payload.reason,
        correlation_id=request.state.correlation_id,
        details={"verification_method": "institution_staff_review"},
    )
    await db.commit()
    return StudentPrnVerificationResponse(
        student_id=student_id, verified=True, verified_at=verified_at
    )


@router.post(
    "/students/{student_id}/manual-recovery",
    response_model=ManualRecoveryHandoff,
    dependencies=[Depends(verify_authenticated_csrf), Depends(require_recent_reauthentication)],
)
async def issue_student_manual_recovery(
    institution_id: UUID,
    student_id: UUID,
    payload: ManualRecoveryRequest,
    request: Request,
    response: Response,
    db: Database,
    principal: InstitutionAdmin,
) -> ManualRecoveryHandoff:
    require_institution(principal, institution_id)
    if email_delivery_configured():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email recovery is active")
    student = await db.scalar(
        select(User)
        .join(InstitutionMembership, InstitutionMembership.user_id == User.id)
        .where(
            User.id == student_id,
            User.role == UserRole.STUDENT.value,
            User.is_active.is_(True),
            InstitutionMembership.institution_id == institution_id,
            InstitutionMembership.role == UserRole.STUDENT.value,
            InstitutionMembership.status == MembershipStatus.ACTIVE.value,
        )
    )
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    token = await issue_password_reset(
        db,
        student.email,
        request.state.correlation_id,
        actor_user_id=principal.user.id,
    )
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    record_audit_event(
        db,
        actor_user_id=principal.user.id,
        institution_id=institution_id,
        event_type="auth.manual_recovery_issued",
        resource_type="user",
        resource_id=str(student.id),
        reason=payload.reason,
        correlation_id=request.state.correlation_id,
        details={
            "identity_check_method": payload.identity_check_method,
            "identity_check_reference": payload.identity_check_reference,
        },
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return ManualRecoveryHandoff(
        reset_code=token,
        expires_in_minutes=get_settings().password_reset_ttl_minutes,
    )


def _csv_cell(value: object | None) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get("/memberships", response_model=MembershipPage)
async def read_memberships(
    institution_id: UUID,
    db: Database,
    principal: InstitutionAdmin,
    query: Annotated[str | None, Query(max_length=320)] = None,
    membership_status: Annotated[
        str | None, Query(pattern=r"^(active|invited|pending|suspended|revoked|graduated)$")
    ] = None,
    role: UserRole | None = None,
    sort: Literal["email", "status", "created_at"] = "email",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> MembershipPage:
    require_institution(principal, institution_id)
    memberships, total = await paginate_memberships(
        db,
        institution_id,
        query=query,
        membership_status=membership_status,
        role=role.value if role else None,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    items = [
        MembershipResponse.model_validate(item).model_copy(
            update={"email": item.user.email, "username": item.user.username}
        )
        for item in memberships
    ]
    return MembershipPage(items=items, page=page, page_size=page_size, total=total)


@router.get("/memberships/export.csv")
async def export_memberships(
    institution_id: UUID,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
    role: UserRole | None = None,
) -> Response:
    require_institution(principal, institution_id)
    memberships = await list_memberships(
        db, institution_id, role=role.value if role else None
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["email", "role", "status", "verified_at"])
    for membership in memberships:
        writer.writerow(
            [
                _csv_cell(membership.user.email),
                _csv_cell(membership.role),
                _csv_cell(membership.status),
                _csv_cell(membership.verified_at.isoformat() if membership.verified_at else None),
            ]
        )
    record_audit_event(
        db,
        event_type="membership.exported",
        actor_user_id=principal.user.id,
        institution_id=institution_id,
        resource_type="institution_membership",
        correlation_id=request.state.correlation_id,
        details={"row_count": len(memberships)},
    )
    await db.commit()
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="campushire-memberships.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/student-access-requests", response_model=list[StudentAccessRequestSummary])
async def read_student_access_requests(
    institution_id: UUID,
    response: Response,
    db: Database,
    principal: InstitutionAdmin,
) -> list[StudentAccessRequestSummary]:
    require_institution(principal, institution_id)
    response.headers["Cache-Control"] = "no-store"
    requests = (
        await db.scalars(
            select(StudentRegistrationRequest)
            .where(
                StudentRegistrationRequest.institution_id == institution_id,
                StudentRegistrationRequest.status == RegistrationStatus.PENDING_APPROVAL.value,
            )
            .order_by(StudentRegistrationRequest.created_at.desc())
            .limit(50)
        )
    ).all()
    return [StudentAccessRequestSummary.model_validate(item) for item in requests]


@router.get("/roster-imports", response_model=list[RosterImportSummary])
async def read_roster_imports(
    institution_id: UUID,
    db: Database,
    principal: InstitutionAdmin,
) -> list[RosterImportSummary]:
    require_institution(principal, institution_id)
    imports = (
        await db.scalars(
            select(RosterImport)
            .where(RosterImport.institution_id == institution_id)
            .order_by(RosterImport.created_at.desc())
            .limit(50)
        )
    ).all()
    return [RosterImportSummary.model_validate(item, from_attributes=True) for item in imports]


@router.get("/invitations", response_model=list[InvitationSummary])
async def read_invitations(
    institution_id: UUID,
    db: Database,
    principal: InstitutionAdmin,
) -> list[InvitationSummary]:
    require_institution(principal, institution_id)
    invitations = await list_invitations(db, institution_id=institution_id)
    return [
        InvitationSummary(
            id=item.id,
            email=item.email,
            enrollment_id=item.enrollment_id,
            full_name=item.full_name,
            role=item.role,
            status=invitation_status(item),
            expires_at=item.expires_at,
            resend_count=item.resend_count,
            created_at=item.created_at,
        )
        for item in invitations
    ]


@router.post(
    "/staff-accounts",
    response_model=StaffAccountResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def provision_staff_account(
    institution_id: UUID,
    payload: StaffAccountCreate,
    request: Request,
    db: Database,
    principal: InstitutionOwner,
) -> StaffAccountResponse:
    require_institution(principal, institution_id)
    try:
        user, membership = await create_staff_account(
            db,
            institution_id=institution_id,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            reason=payload.reason,
            actor_user_id=principal.user.id,
            actor_role=principal.role,
            correlation_id=request.state.correlation_id,
        )
    except StaffAccountConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "staff_account_conflict",
                "message": "An account already exists for that username.",
            },
        ) from None
    except MembershipPermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "membership_permission_denied", "message": str(error)},
        ) from error
    return StaffAccountResponse(
        id=membership.id,
        institution_id=membership.institution_id,
        user_id=membership.user_id,
        email=user.email,
        username=user.username,
        role=membership.role,
        status=membership.status,
        requires_terms_acceptance=user.requires_terms_acceptance,
    )


@router.post(
    "/memberships",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
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
            reason=payload.reason,
            actor_user_id=principal.user.id,
            actor_role=principal.role,
            correlation_id=request.state.correlation_id,
        )
    except MembershipUserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership user was not found"
        ) from error
    except MembershipPermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "membership_permission_denied", "message": str(error)},
        ) from error
    return MembershipResponse.model_validate(membership)


@router.patch(
    "/memberships/{membership_id}",
    response_model=MembershipResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
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
    try:
        membership = await update_membership_status(
            db,
            institution_id=institution_id,
            membership_id=membership_id,
            status=payload.status,
            reason=payload.reason,
            actor_user_id=principal.user.id,
            actor_role=principal.role,
            correlation_id=request.state.correlation_id,
        )
    except MembershipPermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "membership_permission_denied", "message": str(error)},
        ) from error
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membership was not found"
        )
    return MembershipResponse.model_validate(membership)


def _roster_response(
    roster: RosterImport,
    rows: Sequence[RosterImportRow],
) -> RosterImportResponse:
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
    response_model=RosterCommitResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def commit_roster_import(
    institution_id: UUID,
    roster_import_id: UUID,
    request: Request,
    response: Response,
    db: Database,
    principal: InstitutionAdmin,
) -> RosterCommitResponse:
    require_institution(principal, institution_id)
    roster, handoffs = await commit_roster(
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
    response.headers["Cache-Control"] = "no-store"
    return RosterCommitResponse(
        **_roster_response(roster, rows).model_dump(),
        handoffs=[
            InvitationHandoffResponse(
                email=item.email,
                activation_code=item.activation_code,
                expires_at=item.expires_at,
            )
            for item in handoffs
        ],
    )


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=InvitationActionResponse,
    dependencies=[Depends(verify_authenticated_csrf), Depends(require_recent_reauthentication)],
)
async def resend_membership_invitation(
    institution_id: UUID,
    invitation_id: UUID,
    request: Request,
    response: Response,
    db: Database,
    principal: InstitutionAdmin,
) -> InvitationActionResponse:
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
    response.headers["Cache-Control"] = "no-store"
    manual_handoff = not email_delivery_configured()
    return InvitationActionResponse(
        id=invitation.id,
        status=invitation_status(invitation),
        expires_at=invitation.expires_at,
        message=(
            "A replacement code was issued for secure handoff. It was not emailed."
            if manual_handoff
            else "A replacement invitation was queued for delivery."
        ),
        activation_code=token if manual_handoff else None,
    )


@router.post(
    "/invitations/{invitation_id}/revoke",
    response_model=InvitationActionResponse,
    dependencies=[Depends(verify_authenticated_csrf), Depends(require_recent_reauthentication)],
)
async def revoke_membership_invitation(
    institution_id: UUID,
    invitation_id: UUID,
    payload: InvitationRevocationRequest,
    request: Request,
    db: Database,
    principal: InstitutionAdmin,
) -> InvitationActionResponse:
    require_institution(principal, institution_id)
    invitation = await revoke_invitation(
        db,
        institution_id=institution_id,
        invitation_id=invitation_id,
        actor_user_id=principal.user.id,
        reason=payload.reason,
        correlation_id=request.state.correlation_id,
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invitation was not found"
        )
    return InvitationActionResponse(
        id=invitation.id,
        status="revoked",
        expires_at=invitation.expires_at,
        message="The invitation was revoked and can no longer be used.",
    )
