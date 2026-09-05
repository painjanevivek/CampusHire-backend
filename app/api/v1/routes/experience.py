from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select

from app.models.auth import UserRole
from app.models.experience import SavedOpportunityView
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentTenant,
    Database,
    require_permissions,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.experience import queries, service
from app.modules.experience.publishing import PublishPreview, publication_preview
from app.modules.experience.schemas import (
    ApplicationQueuePage,
    CorrectionResponse,
    PreparationResponse,
    ReportResponse,
    RequestCreate,
    RequestResolution,
    RequestResponseCreate,
    SavedViewCreate,
    SavedViewResponse,
)
from app.modules.recruitment.schemas import ApplicationResponse
from app.modules.recruitment.service import RecruitmentError, response_for_application

student_router = APIRouter(dependencies=[Depends(require_roles(UserRole.STUDENT.value))])
admin_router = APIRouter(
    prefix="/admin/recruitment", dependencies=[Depends(require_permissions("recruitment.read"))]
)
write_dependencies = [Depends(verify_authenticated_csrf)]
review_dependencies = [*write_dependencies, Depends(require_permissions("applications.review"))]


def institution(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:
        raise HTTPException(403, "An active institution is required.")
    return principal.institution_id


def failure(error: ValueError) -> HTTPException:
    code = str(error)
    return HTTPException(
        404 if code.endswith("not_found") else 409,
        detail={"code": code, "message": code.replace("_", " ").capitalize()},
    )


@student_router.get(
    "/applications/{application_id}/requests", response_model=list[CorrectionResponse]
)
async def student_requests(
    application_id: UUID, db: Database, tenant: CurrentTenant
) -> list[CorrectionResponse]:
    try:
        return await service.request_page(db, tenant.institution_id, application_id, tenant.user_id)
    except service.ExperienceError as error:
        raise failure(error) from error


@student_router.post(
    "/applications/{application_id}/requests/{request_id}/response",
    response_model=CorrectionResponse,
    dependencies=write_dependencies,
)
async def student_response(
    application_id: UUID,
    request_id: UUID,
    payload: RequestResponseCreate,
    db: Database,
    tenant: CurrentTenant,
) -> CorrectionResponse:
    try:
        result = await service.respond_to_request(
            db, tenant.institution_id, tenant.user_id, application_id, request_id, payload
        )
        await db.commit()
        return result
    except service.ExperienceError as error:
        raise failure(error) from error


@admin_router.get(
    "/applications/{application_id}/requests", response_model=list[CorrectionResponse]
)
async def admin_requests(
    application_id: UUID, db: Database, principal: CurrentPrincipal
) -> list[CorrectionResponse]:
    try:
        return await service.request_page(db, institution(principal), application_id)
    except service.ExperienceError as error:
        raise failure(error) from error


@admin_router.post(
    "/applications/{application_id}/requests",
    response_model=CorrectionResponse,
    dependencies=review_dependencies,
)
async def create_request(
    application_id: UUID, payload: RequestCreate, db: Database, principal: CurrentPrincipal
) -> CorrectionResponse:
    try:
        result = await service.create_request(
            db, institution(principal), principal.user.id, application_id, payload
        )
        await db.commit()
        return result
    except service.ExperienceError as error:
        raise failure(error) from error


@admin_router.post(
    "/applications/{application_id}/requests/{request_id}/resolve",
    response_model=CorrectionResponse,
    dependencies=review_dependencies,
)
async def resolve_request(
    application_id: UUID,
    request_id: UUID,
    payload: RequestResolution,
    db: Database,
    principal: CurrentPrincipal,
) -> CorrectionResponse:
    try:
        result = await service.resolve_request(
            db, institution(principal), principal.user.id, application_id, request_id, payload
        )
        await db.commit()
        return result
    except service.ExperienceError as error:
        raise failure(error) from error


@admin_router.get("/review-queue", response_model=ApplicationQueuePage)
async def review_queue(
    db: Database,
    principal: CurrentPrincipal,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 25,
    application_status: str | None = None,
    drive_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    requests: Annotated[str | None, Query(pattern="^(open|overdue|awaiting_review)$")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    review_pending: bool = False,
) -> ApplicationQueuePage:
    return await queries.review_queue(
        db,
        institution(principal),
        page=page,
        page_size=page_size,
        application_status=application_status,
        drive_id=drive_id,
        start_at=start_at,
        end_at=end_at,
        requests=requests,
        q=q,
        review_pending=review_pending,
    )


@admin_router.get("/applications/{application_id}/requests/{request_id}/events/{event_id}/resume")
async def supplemental_resume(
    application_id: UUID,
    request_id: UUID,
    event_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
) -> Response:
    from app.core.config import get_settings
    from app.models.experience import CorrectionEvent, CorrectionRequest
    from app.models.resume import ResumeVersion
    from app.modules.resumes.storage import ObjectStoreError, build_object_store

    try:
        application = await service.owned_application(db, institution(principal), application_id)
    except service.ExperienceError as error:
        raise failure(error) from error
    version = await db.scalar(
        select(ResumeVersion)
        .join(CorrectionEvent, CorrectionEvent.resume_version_id == ResumeVersion.id)
        .join(CorrectionRequest, CorrectionRequest.id == CorrectionEvent.request_id)
        .where(
            CorrectionEvent.id == event_id,
            CorrectionRequest.id == request_id,
            CorrectionRequest.application_id == application.id,
            CorrectionRequest.institution_id == institution(principal),
            ResumeVersion.user_id == application.student_user_id,
            ResumeVersion.institution_id == institution(principal),
            ResumeVersion.scan_status == "clean",
        )
    )
    if version is None:
        raise HTTPException(404, "Supplemental evidence not found.")
    try:
        data = build_object_store(get_settings()).read(version.storage_key)
    except ObjectStoreError as error:
        raise HTTPException(503, "Supplemental evidence storage is unavailable.") from error
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="reviewed-supplemental-resume.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@admin_router.get("/review-queue/{application_id}", response_model=ApplicationResponse)
async def review_detail(
    application_id: UUID, db: Database, principal: CurrentPrincipal
) -> ApplicationResponse:
    try:
        application = await service.owned_application(db, institution(principal), application_id)
        return await response_for_application(db, application)
    except service.ExperienceError as error:
        raise failure(error) from error


@admin_router.get("/reports", response_model=ReportResponse)
async def report(
    db: Database,
    principal: CurrentPrincipal,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    drive_id: UUID | None = None,
) -> ReportResponse:
    try:
        return await queries.operational_report(
            db, institution(principal), start_at, end_at, drive_id
        )
    except service.ExperienceError as error:
        raise failure(error) from error


@admin_router.get("/drives/{drive_id}/publication-preview", response_model=PublishPreview)
async def preview_publication(
    drive_id: UUID, db: Database, principal: CurrentPrincipal
) -> PublishPreview:
    try:
        return await publication_preview(db, institution(principal), drive_id)
    except service.ExperienceError as error:
        raise failure(error) from error


@student_router.get("/opportunity-views", response_model=list[SavedViewResponse])
async def saved_views(db: Database, tenant: CurrentTenant) -> list[SavedViewResponse]:
    items = (
        await db.scalars(
            select(SavedOpportunityView)
            .where(
                SavedOpportunityView.institution_id == tenant.institution_id,
                SavedOpportunityView.student_user_id == tenant.user_id,
            )
            .order_by(SavedOpportunityView.created_at)
        )
    ).all()
    return [SavedViewResponse.model_validate(item, from_attributes=True) for item in items]


@student_router.post(
    "/opportunity-views", response_model=SavedViewResponse, dependencies=write_dependencies
)
async def create_view(
    payload: SavedViewCreate, db: Database, tenant: CurrentTenant
) -> SavedViewResponse:
    # Lock the owner to serialize the bounded preference collection.
    from app.models.auth import User

    await db.scalar(select(User).where(User.id == tenant.user_id).with_for_update())
    existing = await saved_views(db, tenant)
    if len(existing) >= 20:
        raise HTTPException(422, "Keep at most 20 saved views.")
    item = SavedOpportunityView(
        institution_id=tenant.institution_id,
        student_user_id=tenant.user_id,
        name=payload.name,
        filters=payload.filters,
    )
    db.add(item)
    await db.commit()
    return SavedViewResponse.model_validate(item, from_attributes=True)


@student_router.put(
    "/opportunity-views/{view_id}",
    response_model=SavedViewResponse,
    dependencies=write_dependencies,
)
async def update_view(
    view_id: UUID, payload: SavedViewCreate, db: Database, tenant: CurrentTenant
) -> SavedViewResponse:
    item = await db.scalar(
        select(SavedOpportunityView)
        .where(
            SavedOpportunityView.id == view_id,
            SavedOpportunityView.institution_id == tenant.institution_id,
            SavedOpportunityView.student_user_id == tenant.user_id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "Saved view not found.")
    item.name, item.filters = payload.name, payload.filters
    await db.commit()
    return SavedViewResponse.model_validate(item, from_attributes=True)


@student_router.delete(
    "/opportunity-views/{view_id}", status_code=204, dependencies=write_dependencies
)
async def delete_view(view_id: UUID, db: Database, tenant: CurrentTenant) -> Response:
    item = await db.scalar(
        select(SavedOpportunityView).where(
            SavedOpportunityView.id == view_id,
            SavedOpportunityView.institution_id == tenant.institution_id,
            SavedOpportunityView.student_user_id == tenant.user_id,
        )
    )
    if item is None:
        raise HTTPException(404, "Saved view not found.")
    await db.delete(item)
    await db.commit()
    return Response(status_code=204)


@student_router.get("/opportunities/{role_id}/preparation", response_model=PreparationResponse)
async def preparation(
    role_id: UUID, db: Database, tenant: CurrentTenant, resume_id: UUID | None = None
) -> PreparationResponse:
    try:
        return await queries.preparation(
            db, tenant.institution_id, tenant.user_id, role_id, resume_id
        )
    except (service.ExperienceError, RecruitmentError) as error:
        raise failure(error) from error
