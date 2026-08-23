from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.auth import UserRole
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.recruitment.schemas import (
    ApplicationOverrideCreate,
    ApplicationResponse,
    ApplicationStatusUpdate,
    CompanyCreate,
    CompanyResponse,
    CompanyUpdate,
    DriveCreate,
    DriveResponse,
    DriveUpdate,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    RuleSetCreate,
    RuleSetResponse,
)
from app.modules.recruitment.service import (
    RecruitmentError,
    company_response,
    create_company,
    create_drive,
    create_role,
    create_rule_set,
    drive_response,
    list_admin_applications,
    list_companies,
    list_drives,
    list_roles,
    list_rule_sets,
    override_application,
    publish_role,
    publish_rule_set,
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
    dependencies=[Depends(require_roles(UserRole.TNP_ADMIN.value))],
)


def _http_error(error: RecruitmentError) -> HTTPException:
    code = str(error)
    if code.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in {"company_name_exists"}:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)


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
    dependencies=[Depends(verify_authenticated_csrf)],
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
    dependencies=[Depends(verify_authenticated_csrf)],
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
    dependencies=[Depends(verify_authenticated_csrf)],
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


@router.patch(
    "/drives/{drive_id}",
    response_model=DriveResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
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


@router.post(
    "/drives/{drive_id}/actions/{action}",
    response_model=DriveResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
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
    dependencies=[Depends(verify_authenticated_csrf)],
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
    dependencies=[Depends(verify_authenticated_csrf)],
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
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def publish_admin_role(
    request: Request, role_id: UUID, db: Database, principal: CurrentPrincipal
) -> RoleResponse:
    try:
        role = await publish_role(db, principal.institution_id, role_id)
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
    "/roles/{role_id}/rule-sets",
    response_model=RuleSetResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
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
    dependencies=[Depends(verify_authenticated_csrf)],
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


@router.get("/applications", response_model=list[ApplicationResponse])
async def read_applications(
    db: Database,
    principal: CurrentPrincipal,
    role_id: UUID | None = None,
    application_status: str | None = None,
) -> list[ApplicationResponse]:
    return await list_admin_applications(db, principal.institution_id, role_id, application_status)


@router.post(
    "/applications/{application_id}/status",
    response_model=ApplicationResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
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
    await db.commit()
    return response


@router.post(
    "/applications/{application_id}/override",
    response_model=ApplicationResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
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
    await db.commit()
    return response
