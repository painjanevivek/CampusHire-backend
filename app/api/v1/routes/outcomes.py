from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentTenant,
    Database,
    require_permissions,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.outcomes import service
from app.modules.outcomes.schemas import (
    MetricDefinitionApproval,
    MetricDefinitionCreate,
    MetricDefinitionResponse,
    OutcomeEventCreate,
    OutcomeEventResponse,
)

student_router = APIRouter(dependencies=[Depends(require_roles(UserRole.STUDENT.value))])
tnp_router = APIRouter(
    prefix="/recruitment", dependencies=[Depends(require_permissions("recruitment.read"))]
)
platform_router = APIRouter(
    prefix="/platform", dependencies=[Depends(require_roles(UserRole.PLATFORM_ADMIN.value))]
)


def _institution(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:
        raise HTTPException(403, "An active institution is required.")
    return principal.institution_id


def _failure(error: service.OutcomeError) -> HTTPException:
    code = str(error)
    status = 404 if code.endswith("not_found") else 409
    return HTTPException(status, detail={"code": code, "message": code.replace("_", " ").title()})


@student_router.get(
    "/applications/{application_id}/outcomes", response_model=list[OutcomeEventResponse]
)
async def student_outcome_timeline(
    application_id: UUID, db: Database, tenant: CurrentTenant
) -> list[OutcomeEventResponse]:
    try:
        return await service.list_outcome_events(
            db,
            tenant.institution_id,
            application_id,
            student_user_id=tenant.user_id,
        )
    except service.OutcomeError as error:
        raise _failure(error) from error


@tnp_router.get(
    "/applications/{application_id}/outcomes", response_model=list[OutcomeEventResponse]
)
async def tnp_outcome_timeline(
    application_id: UUID, db: Database, principal: CurrentPrincipal
) -> list[OutcomeEventResponse]:
    try:
        return await service.list_outcome_events(db, _institution(principal), application_id)
    except service.OutcomeError as error:
        raise _failure(error) from error


@tnp_router.post(
    "/applications/{application_id}/outcomes",
    response_model=OutcomeEventResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def record_outcome_event(
    application_id: UUID,
    payload: OutcomeEventCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> OutcomeEventResponse:
    try:
        result = await service.create_outcome_event(
            db,
            _institution(principal),
            principal.user.id,
            application_id,
            payload,
        )
        await db.commit()
        return result
    except service.OutcomeError as error:
        raise _failure(error) from error


@platform_router.get(
    "/institutions/{institution_id}/applications/{application_id}/outcomes",
    response_model=list[OutcomeEventResponse],
)
async def platform_outcome_drillthrough(
    institution_id: UUID,
    application_id: UUID,
    db: Database,
) -> list[OutcomeEventResponse]:
    try:
        return await service.list_outcome_events(db, institution_id, application_id)
    except service.OutcomeError as error:
        raise _failure(error) from error


@platform_router.get(
    "/metric-definitions", response_model=list[MetricDefinitionResponse]
)
async def metric_definitions(db: Database) -> list[MetricDefinitionResponse]:
    return await service.list_metric_definitions(db)


@platform_router.post(
    "/metric-definitions",
    response_model=MetricDefinitionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def create_metric_definition(
    payload: MetricDefinitionCreate, db: Database, principal: CurrentPrincipal
) -> MetricDefinitionResponse:
    result = await service.create_metric_definition(db, principal.user.id, payload)
    await db.commit()
    return result


@platform_router.post(
    "/metric-definitions/{definition_id}/approve",
    response_model=MetricDefinitionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def approve_metric_definition(
    definition_id: UUID,
    payload: MetricDefinitionApproval,
    db: Database,
    principal: CurrentPrincipal,
) -> MetricDefinitionResponse:
    try:
        result = await service.approve_metric_definition(
            db, definition_id, principal.user.id, payload
        )
        await db.commit()
        return result
    except service.OutcomeError as error:
        raise _failure(error) from error
