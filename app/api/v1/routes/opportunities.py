from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from app.models.auth import UserRole
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.recruitment.schemas import (
    ApplicationCreate,
    ApplicationResponse,
    OpportunityPage,
    OpportunityResponse,
    SaveResponse,
)
from app.modules.recruitment.service import (
    RecruitmentError,
    create_application,
    get_opportunity,
    list_opportunities,
    list_student_applications,
    response_for_application,
    toggle_saved,
)

router = APIRouter(dependencies=[Depends(require_roles(UserRole.STUDENT.value))])


def _http_error(error: RecruitmentError) -> HTTPException:
    code = str(error)
    if code.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in {"application_already_exists"}:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)


@router.get("/opportunities", response_model=OpportunityPage)
async def read_opportunities(
    db: Database,
    principal: CurrentPrincipal,
    q: Annotated[str | None, Query(max_length=120)] = None,
    location: Annotated[str | None, Query(max_length=120)] = None,
    work_mode: Annotated[str | None, Query(pattern=r"^(on-site|hybrid|remote)$")] = None,
    skill: Annotated[str | None, Query(max_length=80)] = None,
    saved_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> OpportunityPage:
    return await list_opportunities(
        db,
        principal.institution_id,
        principal.user.id,
        query=q,
        location=location,
        work_mode=work_mode,
        skill=skill,
        saved_only=saved_only,
        page=page,
        page_size=page_size,
    )


@router.get("/opportunities/{role_id}", response_model=OpportunityResponse)
async def read_opportunity(
    role_id: UUID, db: Database, principal: CurrentPrincipal
) -> OpportunityResponse:
    try:
        return await get_opportunity(db, principal.institution_id, principal.user.id, role_id)
    except RecruitmentError as error:
        raise _http_error(error) from error


@router.post(
    "/opportunities/{role_id}/save",
    response_model=SaveResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def save_opportunity(
    role_id: UUID, db: Database, principal: CurrentPrincipal
) -> SaveResponse:
    try:
        saved = await toggle_saved(db, principal.institution_id, principal.user.id, role_id)
    except RecruitmentError as error:
        raise _http_error(error) from error
    await db.commit()
    return SaveResponse(role_id=role_id, saved=saved)


@router.get("/applications", response_model=list[ApplicationResponse])
async def read_student_applications(
    db: Database, principal: CurrentPrincipal
) -> list[ApplicationResponse]:
    return await list_student_applications(db, principal.institution_id, principal.user.id)


@router.post(
    "/applications",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def submit_application(
    request: Request,
    payload: ApplicationCreate,
    db: Database,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)],
) -> ApplicationResponse | JSONResponse:
    try:
        application, replayed = await create_application(
            db,
            principal.institution_id,
            principal.user.id,
            idempotency_key,
            payload,
        )
        response = await response_for_application(db, application)
    except RecruitmentError as error:
        raise _http_error(error) from error
    if not replayed:
        record_audit_event(
            db,
            event_type="application.submitted",
            actor_user_id=principal.user.id,
            institution_id=principal.institution_id,
            resource_type="application",
            resource_id=str(application.id),
            correlation_id=request.state.correlation_id,
            details={
                "role_id": str(application.role_id),
                "resume_version_id": str(application.resume_version_id),
                "eligibility_evaluation_id": str(application.eligibility_evaluation_id),
            },
        )
        await db.commit()
    if replayed:
        return JSONResponse(response.model_dump(mode="json"), status_code=status.HTTP_200_OK)
    return response
