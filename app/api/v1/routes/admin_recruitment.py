from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.config import get_settings
from app.modules.application_packets.service import publish_pending_form_for_role
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_permissions,
    require_recent_reauthentication,
    verify_authenticated_csrf,
)
from app.modules.communications.service import (
    enqueue_email,
    get_preferences,
    record_product_event,
)
from app.modules.engagement.service import upsert_notification
from app.modules.recruitment.schemas import (
    AdminApplicationPage,
    ApplicationAppealResolution,
    ApplicationAppealResponse,
    ApplicationOverrideCreate,
    ApplicationResponse,
    ApplicationStatusUpdate,
    BulkApplicationApplyRequest,
    BulkApplicationApplyResponse,
    BulkApplicationPreviewResponse,
    BulkApplicationStatusRequest,
    CompanyCreate,
    CompanyResponse,
    CompanyUpdate,
    DriveCreate,
    DriveResponse,
    DriveUpdate,
    EligibilityPreviewRequest,
    EligibilityResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    RuleSetCreate,
    RuleSetResponse,
)
from app.modules.recruitment.service import (
    RecruitmentError,
    application_appeal_response,
    apply_bulk_application_status,
    company_response,
    create_company,
    create_drive,
    create_role,
    create_rule_set,
    delete_drive,
    drive_response,
    duplicate_drive,
    list_admin_applications,
    list_companies,
    list_drives,
    list_roles,
    list_rule_sets,
    override_application,
    preview_bulk_application_status,
    preview_role_eligibility,
    publish_role,
    publish_rule_set,
    resolve_application_appeal,
    response_for_application,
    role_response,
    transition_drive,
    update_application_status,
    update_company,
    update_drive,
    update_role,
)

router = APIRouter(
    prefix="/admin/recruitment",
    dependencies=[Depends(require_permissions("recruitment.read"))],
)


def _http_error(error: RecruitmentError) -> HTTPException:
    code = str(error)
    if code.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in {
        "company_name_exists",
        "application_appeal_already_resolved",
        "published_drive_is_immutable",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)


async def _enqueue_application_update(
    db: Database,
    application: ApplicationResponse,
    institution_id: UUID,
    message: str | None,
) -> None:
    preference = await get_preferences(db, institution_id, application.student_user_id)
    role_title = str(application.role_snapshot.get("title", "Placement role"))
    frontend = str(get_settings().frontend_origins[0]).rstrip("/")
    await enqueue_email(
        db,
        institution_id=institution_id,
        recipient_email=application.student_email,
        category="application",
        template_key="application_status",
        variables={
            "role_title": role_title,
            "status": application.status.replace("_", " "),
            "message": message or "Your placement office updated this application.",
            "application_url": f"{frontend}/applications/{application.id}",
        },
        dedupe_key=f"application-status:{application.id}:{application.status}",
        optional_enabled=preference.application_updates,
    )


def _audit(
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
    *,
    event_type: str,
    resource_type: str,
    resource_id: UUID,
    reason: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    record_audit_event(
        db,
        event_type=event_type,
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type=resource_type,
        resource_id=str(resource_id),
        reason=reason,
        correlation_id=request.state.correlation_id,
        details=details,
    )


@router.get("/companies", response_model=list[CompanyResponse])
async def read_companies(db: Database, principal: CurrentPrincipal) -> list[CompanyResponse]:
    return await list_companies(db, principal.institution_id)


@router.post(
    "/companies",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def add_company(
    request: Request, payload: CompanyCreate, db: Database, principal: CurrentPrincipal
) -> CompanyResponse:
    try:
        company = await create_company(db, principal.institution_id, payload)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="company.created",
        resource_type="company",
        resource_id=company.id,
    )
    await db.commit()
    return company_response(company)


@router.patch(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def edit_company(
    request: Request,
    company_id: UUID,
    payload: CompanyUpdate,
    db: Database,
    principal: CurrentPrincipal,
) -> CompanyResponse:
    try:
        company = await update_company(db, principal.institution_id, company_id, payload)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="company.updated",
        resource_type="company",
        resource_id=company.id,
    )
    await db.commit()
    return company_response(company)


@router.get("/drives", response_model=list[DriveResponse])
async def read_drives(db: Database, principal: CurrentPrincipal) -> list[DriveResponse]:
    return await list_drives(db, principal.institution_id)


@router.post(
    "/drives",
    response_model=DriveResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def add_drive(
    request: Request, payload: DriveCreate, db: Database, principal: CurrentPrincipal
) -> DriveResponse:
    try:
        drive = await create_drive(db, principal.institution_id, payload)
        response = await drive_response(db, drive)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="drive.created",
        resource_type="placement_drive",
        resource_id=drive.id,
    )
    await db.commit()
    return response


@router.post(
    "/application-appeals/{appeal_id}/resolution",
    response_model=ApplicationAppealResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("applications.review")),
    ],
)
async def resolve_appeal(
    request: Request,
    appeal_id: UUID,
    payload: ApplicationAppealResolution,
    db: Database,
    principal: CurrentPrincipal,
) -> ApplicationAppealResponse:
    try:
        appeal = await resolve_application_appeal(
            db, principal.institution_id, principal.user.id, appeal_id, payload
        )
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="application.appeal_resolved",
        resource_type="application_appeal",
        resource_id=appeal.id,
        reason=payload.administrator_response,
        details={"status": payload.status, "application_id": str(appeal.application_id)},
    )
    await upsert_notification(
        db,
        institution_id=appeal.institution_id,
        recipient_user_id=appeal.student_user_id,
        event_key=f"application-appeal:{appeal.id}:{payload.status}",
        title=f"Application review request {payload.status}",
        body=payload.administrator_response,
        deep_link=f"/applications/{appeal.application_id}",
        created_by_user_id=principal.user.id,
    )
    await db.commit()
    return application_appeal_response(appeal)


@router.patch(
    "/drives/{drive_id}",
    response_model=DriveResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def edit_drive(
    request: Request,
    drive_id: UUID,
    payload: DriveUpdate,
    db: Database,
    principal: CurrentPrincipal,
) -> DriveResponse:
    try:
        drive = await update_drive(db, principal.institution_id, drive_id, payload)
        response = await drive_response(db, drive)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="drive.updated",
        resource_type="placement_drive",
        resource_id=drive.id,
    )
    await db.commit()
    return response


@router.delete(
    "/drives/{drive_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
        Depends(require_recent_reauthentication),
    ],
)
async def remove_drive(
    request: Request,
    drive_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
) -> None:
    try:
        drive = await delete_drive(db, principal.institution_id, drive_id)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="drive.deleted",
        resource_type="placement_drive",
        resource_id=drive.id,
        details={"title": drive.title, "company_id": str(drive.company_id)},
    )
    await db.commit()


@router.post(
    "/drives/{drive_id}/actions/{action}",
    response_model=DriveResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def change_drive_state(
    request: Request,
    drive_id: UUID,
    action: str,
    db: Database,
    principal: CurrentPrincipal,
) -> DriveResponse:
    try:
        drive = await transition_drive(db, principal.institution_id, drive_id, action)
        response = await drive_response(db, drive)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type=f"drive.{action}",
        resource_type="placement_drive",
        resource_id=drive.id,
        details={"status": drive.status},
    )
    await db.commit()
    return response


@router.post(
    "/drives/{drive_id}/duplicate",
    response_model=DriveResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def duplicate_admin_drive(
    request: Request,
    drive_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
) -> DriveResponse:
    try:
        drive = await duplicate_drive(db, principal.institution_id, drive_id, principal.user.id)
        response = await drive_response(db, drive)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="drive.duplicated",
        resource_type="placement_drive",
        resource_id=drive.id,
        details={"source_drive_id": str(drive_id)},
    )
    await db.commit()
    return response


@router.get("/drives/{drive_id}/roles", response_model=list[RoleResponse])
async def read_roles(
    drive_id: UUID, db: Database, principal: CurrentPrincipal
) -> list[RoleResponse]:
    try:
        return await list_roles(db, principal.institution_id, drive_id)
    except RecruitmentError as error:
        raise _http_error(error) from error


@router.post(
    "/drives/{drive_id}/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def add_role(
    request: Request,
    drive_id: UUID,
    payload: RoleCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> RoleResponse:
    try:
        role = await create_role(db, principal.institution_id, drive_id, payload)
        response = await role_response(db, role)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="role.created",
        resource_type="placement_role",
        resource_id=role.id,
    )
    await db.commit()
    return response


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def edit_role(
    request: Request,
    role_id: UUID,
    payload: RoleUpdate,
    db: Database,
    principal: CurrentPrincipal,
) -> RoleResponse:
    try:
        role = await update_role(db, principal.institution_id, role_id, payload)
        response = await role_response(db, role)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="role.updated",
        resource_type="placement_role",
        resource_id=role.id,
    )
    await db.commit()
    return response


@router.post(
    "/roles/{role_id}/publish",
    response_model=RoleResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def publish_admin_role(
    request: Request, role_id: UUID, db: Database, principal: CurrentPrincipal
) -> RoleResponse:
    try:
        role = await publish_role(db, principal.institution_id, role_id)
        await publish_pending_form_for_role(db, principal.institution_id, role_id)
        response = await role_response(db, role)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="role.published",
        resource_type="placement_role",
        resource_id=role.id,
    )
    await record_product_event(
        db,
        event_name="role_published",
        route_group="admin_drives",
        institution_id=principal.institution_id,
        dedupe_key=f"role-published:{role.id}",
    )
    await db.commit()
    return response


@router.get("/roles/{role_id}/rule-sets", response_model=list[RuleSetResponse])
async def read_rule_sets(
    role_id: UUID, db: Database, principal: CurrentPrincipal
) -> list[RuleSetResponse]:
    try:
        return await list_rule_sets(db, principal.institution_id, role_id)
    except RecruitmentError as error:
        raise _http_error(error) from error


@router.post(
    "/roles/{role_id}/eligibility-preview",
    response_model=EligibilityResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def preview_admin_eligibility(
    role_id: UUID,
    payload: EligibilityPreviewRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> EligibilityResponse:
    try:
        return await preview_role_eligibility(
            db,
            principal.institution_id,
            role_id,
            payload.model_dump(),
        )
    except RecruitmentError as error:
        raise _http_error(error) from error


@router.post(
    "/roles/{role_id}/rule-sets",
    response_model=RuleSetResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def add_rule_set(
    request: Request,
    role_id: UUID,
    payload: RuleSetCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> RuleSetResponse:
    try:
        item = await create_rule_set(
            db, principal.institution_id, role_id, principal.user.id, payload
        )
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="eligibility_rule_set.created",
        resource_type="eligibility_rule_set",
        resource_id=item.id,
        details={"role_id": str(role_id), "version": item.version},
    )
    await db.commit()
    return RuleSetResponse.model_validate(item, from_attributes=True)


@router.post(
    "/roles/{role_id}/rule-sets/{rule_set_id}/publish",
    response_model=RuleSetResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def publish_admin_rule_set(
    request: Request,
    role_id: UUID,
    rule_set_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
) -> RuleSetResponse:
    try:
        item = await publish_rule_set(db, principal.institution_id, role_id, rule_set_id)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="eligibility_rule_set.published",
        resource_type="eligibility_rule_set",
        resource_id=item.id,
        details={"role_id": str(role_id), "version": item.version},
    )
    await db.commit()
    return RuleSetResponse.model_validate(item, from_attributes=True)


@router.get("/applications", response_model=AdminApplicationPage)
async def read_applications(
    db: Database,
    principal: CurrentPrincipal,
    role_id: UUID | None = None,
    application_status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 25,
) -> AdminApplicationPage:
    return await list_admin_applications(
        db,
        principal.institution_id,
        role_id,
        application_status,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/applications/bulk/preview",
    response_model=BulkApplicationPreviewResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def preview_bulk_application_change(
    payload: BulkApplicationStatusRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> BulkApplicationPreviewResponse:
    try:
        return await preview_bulk_application_status(db, principal.institution_id, payload)
    except RecruitmentError as error:
        raise _http_error(error) from error


@router.post(
    "/applications/bulk/status",
    response_model=BulkApplicationApplyResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("applications.bulk")),
        Depends(require_recent_reauthentication),
    ],
)
async def apply_bulk_application_change(
    request: Request,
    payload: BulkApplicationApplyRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> BulkApplicationApplyResponse:
    try:
        applications = await apply_bulk_application_status(
            db, principal.institution_id, principal.user.id, payload
        )
    except RecruitmentError as error:
        raise _http_error(error) from error
    notification_count = 0
    for application in applications:
        application_response = await response_for_application(db, application)
        await upsert_notification(
            db,
            institution_id=application.institution_id,
            recipient_user_id=application.student_user_id,
            event_key=f"application:{application.id}:{payload.status}",
            title=f"Application {payload.status.replace('_', ' ')}",
            body=payload.reason,
            deep_link=f"/applications/{application.id}",
            created_by_user_id=principal.user.id,
        )
        await _enqueue_application_update(
            db, application_response, application.institution_id, payload.reason
        )
        notification_count += 1
    record_audit_event(
        db,
        event_type="application.bulk_status_changed",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="application",
        outcome="success",
        reason=payload.reason,
        correlation_id=request.state.correlation_id,
        details={
            "status": payload.status,
            "updated_count": len(applications),
            "notification_count": notification_count,
        },
    )
    await db.commit()
    return BulkApplicationApplyResponse(
        updated_count=len(applications),
        notification_count=notification_count,
        application_ids=[item.id for item in applications],
    )


@router.post(
    "/applications/{application_id}/status",
    response_model=ApplicationResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("applications.review")),
    ],
)
async def change_application_status(
    request: Request,
    application_id: UUID,
    payload: ApplicationStatusUpdate,
    db: Database,
    principal: CurrentPrincipal,
) -> ApplicationResponse:
    try:
        application = await update_application_status(
            db, principal.institution_id, application_id, principal.user.id, payload
        )
        response = await response_for_application(db, application)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="application.status_changed",
        resource_type="application",
        resource_id=application.id,
        reason=payload.reason,
        details={"status": payload.status},
    )
    await upsert_notification(
        db,
        institution_id=application.institution_id,
        recipient_user_id=application.student_user_id,
        event_key=f"application:{application.id}:{payload.status}",
        title=f"Application {payload.status.replace('_', ' ')}",
        body=payload.reason or "Your placement application status has changed.",
        deep_link=f"/applications/{application.id}",
        created_by_user_id=principal.user.id,
    )
    await _enqueue_application_update(db, response, application.institution_id, payload.reason)
    await db.commit()
    return response


@router.post(
    "/applications/{application_id}/override",
    response_model=ApplicationResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("applications.override")),
        Depends(require_recent_reauthentication),
    ],
)
async def override_application_decision(
    request: Request,
    application_id: UUID,
    payload: ApplicationOverrideCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> ApplicationResponse:
    try:
        application = await override_application(
            db, principal.institution_id, application_id, principal.user.id, payload
        )
        response = await response_for_application(db, application)
    except RecruitmentError as error:
        raise _http_error(error) from error
    _audit(
        request,
        db,
        principal,
        event_type="application.decision_overridden",
        resource_type="application",
        resource_id=application.id,
        reason=payload.reason,
        details={
            "status": payload.status,
            "policy_reference": payload.policy_reference or "not_provided",
        },
    )
    await upsert_notification(
        db,
        institution_id=application.institution_id,
        recipient_user_id=application.student_user_id,
        event_key=f"application:{application.id}:override:{payload.status}",
        title=f"Application {payload.status.replace('_', ' ')}",
        body=payload.reason,
        deep_link=f"/applications/{application.id}",
        created_by_user_id=principal.user.id,
    )
    await db.commit()
    return response
