from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.models.auth import (
    InstitutionRegistrationRequest,
    PlatformAdminAssignment,
    RegistrationStatus,
)
from app.modules.audit.schemas import AuditEventPage
from app.modules.audit.service import list_audit_events
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
)
from app.modules.institutions.service import (
    MembershipPermissionError,
    StaffAccountConflictError,
    create_staff_account,
    update_membership_status,
)
from app.modules.platform_admin.schemas import (
    InstitutionStatusChange,
    PlatformAdminAssignmentResponse,
    PlatformAdminTransferRequest,
    PlatformDashboardSummary,
    PlatformHealthSummary,
    PlatformInstitutionDetail,
    PlatformInstitutionPage,
    PlatformReportSummary,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    PlatformStaffAccount,
    PlatformStaffAccountCreate,
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
