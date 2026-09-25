import csv
import io
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth import (
    TNP_ROLE_VALUES,
    Institution,
    InstitutionRegistrationRequest,
    PlatformAdminAssignment,
    RegistrationStatus,
    User,
)
from app.modules.audit.schemas import AuditEventPage
from app.modules.audit.service import list_audit_events, record_audit_event
from app.modules.auth.dependencies import (
    AuthenticatedPrincipal,
    Database,
    require_permissions,
    require_recent_reauthentication,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.auth.registration import RegistrationConflictError, decide_institution_registration
from app.modules.auth.schemas import (
    InstitutionRegistrationDecision,
    InstitutionRegistrationResponse,
    ManualRecoveryHandoff,
    ManualRecoveryRequest,
)
from app.modules.auth.security import normalize_username
from app.modules.auth.service import issue_password_reset
from app.modules.communications.service import email_delivery_configured
from app.modules.institutions.lifecycle import ProvisionConflictError, provision_institution
from app.modules.institutions.schemas import (
    InstitutionProvisionRequest,
    InstitutionProvisionResponse,
)
from app.modules.institutions.service import (
    MembershipPermissionError,
    MembershipUserNotFoundError,
    StaffAccountConflictError,
    create_staff_account,
    update_membership_status,
    verify_membership,
)
from app.modules.platform_admin.reports import (
    get_application_evidence,
    list_drive_applicants,
    list_drive_groups,
)
from app.modules.platform_admin.schemas import (
    InstitutionStatusChange,
    PlatformAdminAssignmentResponse,
    PlatformAdminTransferRequest,
    PlatformApplicationEvidence,
    PlatformDashboardSummary,
    PlatformDriveApplicantPage,
    PlatformDriveGroupPage,
    PlatformHealthSummary,
    PlatformInstitutionDetail,
    PlatformInstitutionPage,
    PlatformNoticeCreate,
    PlatformNoticeDelivery,
    PlatformReportSummary,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    PlatformStaffAccount,
    PlatformStaffAccountCreate,
    PlatformStaffAssignmentCreate,
    PlatformStaffStatusChange,
)
from app.modules.platform_admin.service import (
    PlatformAdminAssignmentError,
    change_institution_status,
    list_platform_staff_accounts,
    paginate_platform_institutions,
    platform_dashboard_summary,
    platform_health_summary,
    platform_institution_detail,
    platform_report_summary,
    platform_settings,
    publish_platform_notice,
    transfer_platform_admin,
    update_platform_settings,
)
from app.modules.recruitment.schemas import (
    AdminApplicationPage,
    ApplicationAppealResponse,
    ApplicationResponse,
    CaseAssignmentRequest,
)
from app.modules.recruitment.service import (
    RecruitmentError,
    application_appeal_response,
    assign_appeal_case,
    assign_application_case,
    list_admin_applications,
    response_for_application,
)

router = APIRouter(
    prefix="/platform",
    dependencies=[Depends(require_roles("platform_admin"))],
)
PlatformAdmin = Annotated[AuthenticatedPrincipal, Depends(require_roles("platform_admin"))]


@router.get(
    "/dashboard",
    response_model=PlatformDashboardSummary,
    dependencies=[Depends(require_permissions("platform.dashboard.read"))],
)
async def read_platform_dashboard(db: Database) -> PlatformDashboardSummary:
    return PlatformDashboardSummary.model_validate(await platform_dashboard_summary(db))


@router.post(
    "/notices",
    response_model=PlatformNoticeDelivery,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permissions("platform.notices.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def send_platform_notice(
    payload: PlatformNoticeCreate,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> PlatformNoticeDelivery:
    return await publish_platform_notice(
        db,
        payload=payload,
        actor_user_id=principal.user.id,
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/institutions",
    response_model=PlatformInstitutionPage,
    dependencies=[Depends(require_permissions("platform.institutions.read"))],
)
async def read_platform_institutions(
    db: Database,
    query: Annotated[str | None, Query(max_length=200)] = None,
    is_active: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> PlatformInstitutionPage:
    items, total = await paginate_platform_institutions(
        db, query=query, is_active=is_active, page=page, page_size=page_size
    )
    return PlatformInstitutionPage(items=items, page=page, page_size=page_size, total=total)


@router.post(
    "/institutions",
    response_model=InstitutionProvisionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permissions("platform.institutions.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def provision_platform_institution(
    payload: InstitutionProvisionRequest,
    request: Request,
    response: Response,
    db: Database,
    principal: PlatformAdmin,
) -> InstitutionProvisionResponse:
    try:
        result = await provision_institution(
            db,
            code=payload.institution_code,
            name=payload.institution_name,
            admin_email=str(payload.admin_email),
            correlation_id=request.state.correlation_id,
            actor_user_id=principal.user.id,
        )
    except ProvisionConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "institution_conflict",
                "message": "Institution provisioning conflicts with an existing record.",
            },
        ) from None
    response.headers["Cache-Control"] = "no-store"
    return InstitutionProvisionResponse(
        institution_id=result.institution.id,
        admin_invitation_id=result.invitation.id,
        admin_invitation_token=result.raw_token,
        expires_at=result.invitation.expires_at,
    )


@router.get(
    "/institutions/{institution_id}",
    response_model=PlatformInstitutionDetail,
    dependencies=[Depends(require_permissions("platform.institutions.read"))],
)
async def read_platform_institution(
    institution_id: UUID, db: Database
) -> PlatformInstitutionDetail:
    item = await platform_institution_detail(db, institution_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
    return PlatformInstitutionDetail.model_validate(item)


@router.get(
    "/institutions/{institution_id}/applications",
    response_model=AdminApplicationPage,
    dependencies=[Depends(require_permissions("platform.records.read"))],
)
async def read_platform_institution_applications(
    institution_id: UUID,
    db: Database,
    application_status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> AdminApplicationPage:
    """Read institution application evidence without granting placement mutations."""
    return await list_admin_applications(
        db,
        institution_id,
        None,
        application_status,
        page=page,
        page_size=page_size,
        actor_role="platform_admin",
    )


@router.patch(
    "/institutions/{institution_id}/status",
    response_model=PlatformInstitutionDetail,
    dependencies=[
        Depends(require_permissions("platform.institutions.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def set_platform_institution_status(
    institution_id: UUID,
    payload: InstitutionStatusChange,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> PlatformInstitutionDetail:
    try:
        item = await change_institution_status(
            db,
            institution_id=institution_id,
            is_active=payload.is_active,
            reason=payload.reason,
            actor_user_id=principal.user.id,
            correlation_id=request.state.correlation_id,
            expected_updated_at=payload.expected_updated_at,
        )
    except PlatformAdminAssignmentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "stale_write", "message": str(error)},
        ) from error
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
    detail = await platform_institution_detail(db, institution_id)
    return PlatformInstitutionDetail.model_validate(detail)


@router.get(
    "/institutions/{institution_id}/staff-accounts",
    response_model=list[PlatformStaffAccount],
    dependencies=[Depends(require_permissions("platform.institutions.read"))],
)
async def read_platform_staff_accounts(
    institution_id: UUID, db: Database
) -> list[PlatformStaffAccount]:
    return [
        PlatformStaffAccount.model_validate(item)
        for item in await list_platform_staff_accounts(db, institution_id)
    ]


@router.post(
    "/institutions/{institution_id}/staff-accounts",
    response_model=PlatformStaffAccount,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permissions("platform.staff.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def provision_platform_staff_account(
    institution_id: UUID,
    payload: PlatformStaffAccountCreate,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> PlatformStaffAccount:
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
            detail={"code": "staff_account_conflict", "message": "Username already exists."},
        ) from None
    return PlatformStaffAccount(
        id=membership.id,
        institution_id=membership.institution_id,
        user_id=membership.user_id,
        username=user.username,
        email=user.email,
        role=membership.role,
        status=membership.status,
        requires_terms_acceptance=user.requires_terms_acceptance,
    )


@router.post(
    "/institutions/{institution_id}/staff-assignments",
    response_model=PlatformStaffAccount,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_permissions("platform.staff.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def assign_existing_platform_staff(
    institution_id: UUID,
    payload: PlatformStaffAssignmentCreate,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> PlatformStaffAccount:
    if await db.get(Institution, institution_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Institution not found")
    user_id = payload.user_id
    if payload.username is not None:
        user_id = await db.scalar(
            select(User.id).where(User.username == normalize_username(payload.username))
        )
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="T&P account not found")
    try:
        membership = await verify_membership(
            db,
            institution_id=institution_id,
            user_id=user_id,
            role=payload.role,
            reason=payload.reason,
            actor_user_id=principal.user.id,
            actor_role=principal.role,
            correlation_id=request.state.correlation_id,
        )
    except MembershipUserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="T&P account not found"
        ) from None
    except MembershipPermissionError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "staff_assignment_denied", "message": str(error)},
        ) from None
    items = await list_platform_staff_accounts(db, institution_id)
    item = next(record for record in items if record["id"] == membership.id)
    return PlatformStaffAccount.model_validate(item)


@router.post(
    "/staff-accounts/{user_id}/manual-recovery",
    response_model=ManualRecoveryHandoff,
    dependencies=[
        Depends(require_permissions("platform.staff.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def issue_staff_manual_recovery(
    user_id: UUID,
    payload: ManualRecoveryRequest,
    request: Request,
    response: Response,
    db: Database,
    principal: PlatformAdmin,
) -> ManualRecoveryHandoff:
    if email_delivery_configured():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email recovery is active")
    staff = await db.scalar(
        select(User).where(
            User.id == user_id,
            User.role.in_(TNP_ROLE_VALUES),
            User.is_active.is_(True),
        )
    )
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="T&P account not found")
    token = await issue_password_reset(
        db,
        staff.email,
        request.state.correlation_id,
        actor_user_id=principal.user.id,
    )
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="T&P account not found")
    record_audit_event(
        db,
        actor_user_id=principal.user.id,
        event_type="auth.manual_recovery_issued",
        resource_type="user",
        resource_id=str(staff.id),
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


@router.patch(
    "/institutions/{institution_id}/staff-accounts/{membership_id}",
    response_model=PlatformStaffAccount,
    dependencies=[
        Depends(require_permissions("platform.staff.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def change_platform_staff_access(
    institution_id: UUID,
    membership_id: UUID,
    payload: PlatformStaffStatusChange,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> PlatformStaffAccount:
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
            role=payload.role,
        )
    except MembershipPermissionError as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(error)) from error
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff account not found")
    items = await list_platform_staff_accounts(db, institution_id)
    item = next(record for record in items if record["id"] == membership_id)
    return PlatformStaffAccount.model_validate(item)


@router.post(
    "/institutions/{institution_id}/applications/{application_id}/assignment",
    response_model=ApplicationResponse,
    dependencies=[
        Depends(require_permissions("platform.staff.manage")),
        Depends(verify_authenticated_csrf),
    ],
)
async def reassign_platform_application(
    institution_id: UUID,
    application_id: UUID,
    payload: CaseAssignmentRequest,
    db: Database,
    principal: PlatformAdmin,
) -> ApplicationResponse:
    try:
        application = await assign_application_case(
            db,
            institution_id=institution_id,
            application_id=application_id,
            actor_user_id=principal.user.id,
            payload=payload,
        )
    except RecruitmentError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await db.commit()
    return await response_for_application(db, application)


@router.post(
    "/institutions/{institution_id}/application-appeals/{appeal_id}/assignment",
    response_model=ApplicationAppealResponse,
    dependencies=[
        Depends(require_permissions("platform.staff.manage")),
        Depends(verify_authenticated_csrf),
    ],
)
async def reassign_platform_appeal(
    institution_id: UUID,
    appeal_id: UUID,
    payload: CaseAssignmentRequest,
    db: Database,
    principal: PlatformAdmin,
) -> ApplicationAppealResponse:
    try:
        appeal = await assign_appeal_case(
            db,
            institution_id=institution_id,
            appeal_id=appeal_id,
            actor_user_id=principal.user.id,
            payload=payload,
        )
    except RecruitmentError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    await db.commit()
    return application_appeal_response(appeal)


@router.get(
    "/institution-registration-requests",
    response_model=list[InstitutionRegistrationResponse],
    dependencies=[Depends(require_permissions("platform.institutions.manage"))],
)
async def read_platform_registration_requests(
    db: Database,
) -> list[InstitutionRegistrationResponse]:
    records = (
        await db.scalars(
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
    ).all()
    return [InstitutionRegistrationResponse.model_validate(item) for item in records]


@router.post(
    "/institution-registration-requests/{request_id}/decision",
    response_model=InstitutionRegistrationResponse,
    dependencies=[
        Depends(require_permissions("platform.institutions.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def decide_platform_registration_request(
    request_id: UUID,
    payload: InstitutionRegistrationDecision,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> InstitutionRegistrationResponse:
    try:
        item = await decide_institution_registration(
            db,
            request_id=request_id,
            approve=payload.decision == "approve",
            reason=payload.reason,
            correlation_id=request.state.correlation_id,
            reviewed_by_user_id=principal.user.id,
        )
    except RegistrationConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": str(error), "message": "The request cannot be processed."},
        ) from error
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    return InstitutionRegistrationResponse.model_validate(item)


@router.get(
    "/reports/summary",
    response_model=PlatformReportSummary,
    dependencies=[Depends(require_permissions("platform.reports.read"))],
)
async def read_platform_report_summary(db: Database) -> PlatformReportSummary:
    return PlatformReportSummary.model_validate(await platform_report_summary(db))


@router.get(
    "/reports/drive-groups",
    response_model=PlatformDriveGroupPage,
    dependencies=[Depends(require_permissions("platform.reports.read"))],
)
async def read_platform_drive_groups(
    db: Database,
    active_only: bool = True,
    institution_id: UUID | None = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PlatformDriveGroupPage:
    return await list_drive_groups(
        db, active_only=active_only, institution_id=institution_id,
        query=query, page=page, page_size=page_size,
    )


@router.get(
    "/reports/drive-applicants",
    response_model=PlatformDriveApplicantPage,
    dependencies=[Depends(require_permissions("platform.reports.read", "platform.records.read"))],
)
async def read_platform_drive_applicants(
    db: Database,
    company_name: Annotated[str, Query(min_length=1, max_length=200)],
    drive_title: Annotated[str, Query(min_length=1, max_length=200)],
    cycle_year: Annotated[int, Query(ge=2000, le=2100)],
    institution_id: UUID | None = None,
    drive_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PlatformDriveApplicantPage:
    return await list_drive_applicants(
        db, company_name=company_name, drive_title=drive_title, cycle_year=cycle_year,
        institution_id=institution_id, drive_id=drive_id, page=page, page_size=page_size,
    )


@router.get(
    "/reports/applications/{application_id}",
    response_model=PlatformApplicationEvidence,
    dependencies=[Depends(require_permissions("platform.reports.read", "platform.records.read"))],
)
async def read_platform_application_evidence(
    application_id: UUID, db: Database,
) -> PlatformApplicationEvidence:
    evidence = await get_application_evidence(db, application_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return evidence


def _safe_csv_cell(value: object | None) -> str:
    cell = "" if value is None else str(value)
    normalized = cell.lstrip(" \t\r\n")
    return f"'{cell}" if normalized.startswith(("=", "+", "-", "@")) else cell


@router.get(
    "/reports/drive-applicants.csv",
    dependencies=[Depends(require_permissions(
        "platform.reports.read", "platform.records.read", "platform.reports.export"
    ))],
)
async def export_platform_drive_applicants(
    request: Request,
    db: Database,
    principal: PlatformAdmin,
    company_name: Annotated[str, Query(min_length=1, max_length=200)],
    drive_title: Annotated[str, Query(min_length=1, max_length=200)],
    cycle_year: Annotated[int, Query(ge=2000, le=2100)],
    institution_id: UUID | None = None,
    drive_id: UUID | None = None,
) -> StreamingResponse:
    async def stream_csv() -> AsyncIterator[str]:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow([
            "Student name", "PRN", "PRN verified", "Institution", "Company", "Drive",
            "Role", "Application status", "Submitted at", "Application ID", "Drive ID",
        ])
        yield output.getvalue()
        page = 1
        total = 0
        completed = False
        try:
            while True:
                result = await list_drive_applicants(
                    db, company_name=company_name, drive_title=drive_title,
                    cycle_year=cycle_year, institution_id=institution_id,
                    drive_id=drive_id, page=page, page_size=500,
                )
                for item in result.items:
                    output.seek(0)
                    output.truncate(0)
                    writer.writerow([_safe_csv_cell(value) for value in (
                        item.student_name, item.prn, "yes" if item.prn_verified else "no",
                        item.institution_name, company_name, drive_title, item.role_title,
                        item.application_status, item.submitted_at.isoformat(),
                        item.application_id, item.drive_id,
                    )])
                    total += 1
                    yield output.getvalue()
                if page * 500 >= result.total:
                    break
                page += 1
            completed = True
        finally:
            record_audit_event(
                db, actor_user_id=principal.user.id, institution_id=institution_id,
                event_type="platform.report.exported", resource_type="drive_applicants",
                resource_id=str(drive_id) if drive_id else None,
                correlation_id=request.state.correlation_id,
                outcome="success" if completed else "failure",
                details={"row_count": total, "cycle_year": cycle_year,
                         "institution_id": str(institution_id) if institution_id else None},
            )
            await db.commit()

    return StreamingResponse(
        stream_csv(), media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="campushire-drive-applicants.csv"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/system-health",
    response_model=PlatformHealthSummary,
    dependencies=[Depends(require_permissions("platform.operations.read"))],
)
async def read_platform_system_health(db: Database) -> PlatformHealthSummary:
    return PlatformHealthSummary.model_validate(await platform_health_summary(db))


@router.get(
    "/audit/events",
    response_model=AuditEventPage,
    dependencies=[Depends(require_permissions("platform.audit.read"))],
)
async def read_platform_audit_events(
    db: Database,
    institution_id: UUID | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AuditEventPage:
    return await list_audit_events(db, institution_id, page=page, page_size=page_size, sort="desc")


@router.get(
    "/settings",
    response_model=PlatformSettingsResponse,
    dependencies=[Depends(require_permissions("platform.settings.read"))],
)
async def read_platform_settings(db: Database) -> PlatformSettingsResponse:
    return PlatformSettingsResponse.model_validate(await platform_settings(db))


@router.patch(
    "/settings",
    response_model=PlatformSettingsResponse,
    dependencies=[
        Depends(require_permissions("platform.settings.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def set_platform_settings(
    payload: PlatformSettingsUpdate,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> PlatformSettingsResponse:
    values = payload.model_dump(exclude_none=True)
    await update_platform_settings(
        db,
        values=values,
        actor_user_id=principal.user.id,
        correlation_id=request.state.correlation_id,
    )
    return PlatformSettingsResponse.model_validate(await platform_settings(db))


@router.get(
    "/admin-assignment",
    response_model=PlatformAdminAssignmentResponse,
    dependencies=[Depends(require_permissions("platform.settings.read"))],
)
async def read_platform_admin_assignment(db: Database) -> PlatformAdminAssignmentResponse:
    assignment = await db.get(PlatformAdminAssignment, 1)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not assigned")
    return PlatformAdminAssignmentResponse.model_validate(assignment)


@router.post(
    "/admin-assignment/transfer",
    response_model=PlatformAdminAssignmentResponse,
    dependencies=[
        Depends(require_permissions("platform.settings.manage")),
        Depends(verify_authenticated_csrf),
        Depends(require_recent_reauthentication),
    ],
)
async def transfer_platform_admin_assignment(
    payload: PlatformAdminTransferRequest,
    request: Request,
    db: Database,
    principal: PlatformAdmin,
) -> PlatformAdminAssignmentResponse:
    try:
        assignment = await transfer_platform_admin(
            db,
            user_id=payload.user_id,
            reason=payload.reason,
            actor_user_id=principal.user.id,
            correlation_id=request.state.correlation_id,
            expected_revision=payload.expected_revision,
        )
    except PlatformAdminAssignmentError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "admin_transfer_conflict", "message": str(error)},
        ) from error
    return PlatformAdminAssignmentResponse.model_validate(assignment)
