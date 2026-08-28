import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from app.core.config import get_settings
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentTenant,
    Database,
    require_permissions,
    verify_authenticated_csrf,
)
from app.modules.communications.schemas import (
    BounceEventCreate,
    CommunicationPreferencesResponse,
    CommunicationPreferencesUpdate,
    EmailDeliveryPage,
    EmailDeliveryResponse,
    FunnelResponse,
    ServiceStatusResponse,
    SupportRequestCreate,
    SupportRequestResponse,
)
from app.modules.communications.service import (
    create_support_request,
    delivery_response,
    funnel_metrics,
    get_preferences,
    list_email_deliveries,
    preference_response,
    record_bounce,
    retry_email,
    update_preferences,
)

router = APIRouter()


def _institution(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution context required")
    return principal.institution_id


@router.get("/service-status", response_model=ServiceStatusResponse)
async def read_service_status() -> ServiceStatusResponse:
    settings = get_settings()
    return ServiceStatusResponse(
        status="maintenance" if settings.maintenance_message else "operational",
        maintenance_message=settings.maintenance_message,
        transactional_email="configured" if settings.email_smtp_host else "degraded",
    )


@router.get(
    "/communications/preferences",
    response_model=CommunicationPreferencesResponse,
)
async def read_preferences(db: Database, tenant: CurrentTenant) -> CommunicationPreferencesResponse:
    return preference_response(await get_preferences(db, tenant.institution_id, tenant.user_id))


@router.put(
    "/communications/preferences",
    response_model=CommunicationPreferencesResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def write_preferences(
    payload: CommunicationPreferencesUpdate,
    db: Database,
    tenant: CurrentTenant,
) -> CommunicationPreferencesResponse:
    return await update_preferences(db, tenant.institution_id, tenant.user_id, payload)


@router.post(
    "/support/requests",
    response_model=SupportRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def submit_support_request(
    payload: SupportRequestCreate,
    db: Database,
    principal: CurrentPrincipal,
) -> SupportRequestResponse:
    return await create_support_request(db, principal.institution_id, payload)


@router.get(
    "/admin/communications/email-deliveries",
    response_model=EmailDeliveryPage,
    dependencies=[Depends(require_permissions("operations.read"))],
)
async def read_email_deliveries(
    db: Database,
    principal: CurrentPrincipal,
    delivery_status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EmailDeliveryPage:
    return await list_email_deliveries(
        db, _institution(principal), delivery_status, limit
    )


@router.post(
    "/admin/communications/email-deliveries/{delivery_id}/retry",
    response_model=EmailDeliveryResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("operations.manage")),
    ],
)
async def retry_failed_email(
    delivery_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
) -> EmailDeliveryResponse:
    try:
        item = await retry_email(db, _institution(principal), delivery_id)
    except ValueError as error:
        code = str(error)
        http_status = 404 if code.endswith("not_found") else 409
        raise HTTPException(status_code=http_status, detail=code) from error
    await db.commit()
    return delivery_response(item)


@router.get(
    "/admin/analytics/funnel",
    response_model=FunnelResponse,
    dependencies=[Depends(require_permissions("audit.read"))],
)
async def read_funnel(
    db: Database,
    principal: CurrentPrincipal,
    window_days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> FunnelResponse:
    return await funnel_metrics(db, _institution(principal), window_days)


@router.post("/operator/email/bounce", response_model=EmailDeliveryResponse)
async def receive_email_bounce(
    payload: BounceEventCreate,
    db: Database,
    x_email_webhook_key: Annotated[str | None, Header()] = None,
) -> EmailDeliveryResponse:
    configured = get_settings().email_delivery_webhook_key
    if (
        configured is None
        or x_email_webhook_key is None
        or not secrets.compare_digest(configured, x_email_webhook_key)
    ):
        raise HTTPException(status_code=403, detail="Email webhook access denied")
    try:
        return delivery_response(await record_bounce(db, payload.provider_message_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
