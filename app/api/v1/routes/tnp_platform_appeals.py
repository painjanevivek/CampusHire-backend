from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.rate_limit import enforce_fixed_window_limit
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.platform_admin.appeals import (
    TnpAppealCreate,
    TnpAppealPage,
    TnpAppealResponse,
    TnpAppealStatusUpdate,
    list_appeals,
    resolve_appeal,
    submit_appeal,
)

tnp_router = APIRouter(
    prefix="/tnp/platform-appeals",
    dependencies=[Depends(require_roles("tnp_owner", "tnp_admin"))],
)
platform_router = APIRouter(
    prefix="/platform/tnp-appeals",
    dependencies=[Depends(require_roles("platform_admin"))],
)


@tnp_router.get("", response_model=TnpAppealPage)
async def read_my_appeals(db: Database, principal: CurrentPrincipal) -> TnpAppealPage:
    return await list_appeals(db, submitted_by_user_id=principal.user.id)


@tnp_router.post(
    "", response_model=TnpAppealResponse, status_code=201,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def create_appeal(
    payload: TnpAppealCreate, request: Request, db: Database, principal: CurrentPrincipal,
) -> TnpAppealResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="An institution membership is required")
    await enforce_fixed_window_limit(
        request, namespace="tnp-platform-appeal", identity=str(principal.user.id),
        limit=5, unavailable_detail="Appeals are temporarily unavailable.",
    )
    return await submit_appeal(
        db, institution_id=principal.institution_id, user_id=principal.user.id,
        payload=payload, correlation_id=request.state.correlation_id,
    )


@platform_router.get("", response_model=TnpAppealPage)
async def read_platform_appeals(db: Database) -> TnpAppealPage:
    return await list_appeals(db)


@platform_router.patch(
    "/{appeal_id}", response_model=TnpAppealResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_platform_appeal(
    appeal_id: UUID, payload: TnpAppealStatusUpdate, request: Request,
    db: Database, principal: CurrentPrincipal,
) -> TnpAppealResponse:
    del payload
    updated = await resolve_appeal(
        db, appeal_id=appeal_id, actor_user_id=principal.user.id,
        correlation_id=request.state.correlation_id,
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appeal not found")
    return updated
