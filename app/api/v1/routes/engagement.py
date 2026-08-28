from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.models.auth import UserRole
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentTenant,
    Database,
    require_permissions,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.communications.service import record_product_event
from app.modules.engagement.schemas import (
    DashboardResponse,
    NotificationCreate,
    NotificationPage,
    NotificationResponse,
    RoadmapAvailabilityResponse,
    RoadmapProgressUpdate,
    RoadmapResponse,
    RoadmapSelection,
    RoadmapTemplateResponse,
)
from app.modules.engagement.service import (
    EngagementError,
    current_roadmap,
    dashboard,
    list_notifications,
    list_templates,
    mark_notification_read,
    publish_notification,
    roadmap_availability,
    select_roadmap,
    update_roadmap_progress,
)

student_router = APIRouter(dependencies=[Depends(require_roles(UserRole.STUDENT.value))])
admin_router = APIRouter(
    prefix="/admin/notifications",
    dependencies=[Depends(require_permissions("recruitment.read"))],
)


def _error(error: EngagementError) -> HTTPException:
    code = str(error)
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND
        if code.endswith("_not_found")
        else status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=code,
    )


@student_router.get("/dashboard", response_model=DashboardResponse)
async def read_dashboard(db: Database, tenant: CurrentTenant) -> DashboardResponse:
    response = await dashboard(db, tenant.institution_id, tenant.user_id)
    await db.commit()
    return response


@student_router.get("/roadmaps/templates", response_model=list[RoadmapTemplateResponse])
async def read_roadmap_templates(db: Database) -> list[RoadmapTemplateResponse]:
    response = await list_templates(db)
    await db.commit()
    return response


@student_router.get("/roadmaps/availability", response_model=RoadmapAvailabilityResponse)
async def read_roadmap_availability(
    db: Database, tenant: CurrentTenant
) -> RoadmapAvailabilityResponse:
    response = await roadmap_availability(db, tenant.institution_id, tenant.user_id)
    await db.commit()
    return response


@student_router.get("/roadmaps/current", response_model=RoadmapResponse | None)
async def read_current_roadmap(db: Database, tenant: CurrentTenant) -> RoadmapResponse | None:
    return await current_roadmap(db, tenant.institution_id, tenant.user_id)


@student_router.post(
    "/roadmaps/select",
    response_model=RoadmapResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def choose_roadmap(
    payload: RoadmapSelection, db: Database, tenant: CurrentTenant
) -> RoadmapResponse:
    try:
        response = await select_roadmap(
            db, tenant.institution_id, tenant.user_id, payload.template_id
        )
    except EngagementError as error:
        raise _error(error) from error
    await record_product_event(
        db,
        event_name="roadmap_selected",
        route_group="roadmap",
        institution_id=tenant.institution_id,
        dedupe_key=f"roadmap-selected:{tenant.user_id}",
    )
    await db.commit()
    return response


@student_router.post(
    "/roadmaps/nodes/{node_key}",
    response_model=RoadmapResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def record_roadmap_progress(
    node_key: str,
    payload: RoadmapProgressUpdate,
    db: Database,
    tenant: CurrentTenant,
) -> RoadmapResponse:
    try:
        response = await update_roadmap_progress(
            db, tenant.institution_id, tenant.user_id, node_key, payload
        )
    except EngagementError as error:
        raise _error(error) from error
    await db.commit()
    return response


@student_router.get("/notifications", response_model=NotificationPage)
async def read_notifications(db: Database, tenant: CurrentTenant) -> NotificationPage:
    return await list_notifications(db, tenant.institution_id, tenant.user_id)


@student_router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def read_notification(
    notification_id: UUID, db: Database, tenant: CurrentTenant
) -> NotificationResponse:
    try:
        item = await mark_notification_read(
            db, tenant.institution_id, tenant.user_id, notification_id
        )
    except EngagementError as error:
        raise _error(error) from error
    await db.commit()
    await db.refresh(item)
    return NotificationResponse.model_validate(item, from_attributes=True)


@admin_router.post(
    "",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def create_notification(
    payload: NotificationCreate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> NotificationResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    try:
        item = await publish_notification(db, principal.institution_id, principal.user.id, payload)
    except EngagementError as error:
        raise _error(error) from error
    record_audit_event(
        db,
        event_type="notification.published",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="notification",
        resource_id=str(item.id),
        correlation_id=request.state.correlation_id,
        details={"event_key": item.event_key, "recipient_user_id": str(item.recipient_user_id)},
    )
    await db.commit()
    await db.refresh(item)
    return NotificationResponse.model_validate(item, from_attributes=True)
