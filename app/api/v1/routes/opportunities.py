from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.models.auth import UserRole
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentTenant,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.recruitment.schemas import (
    ApplicationAppealCreate,
    ApplicationAppealResponse,
    ApplicationCreate,
    ApplicationResponse,
    ApplicationWithdrawal,
    OpportunityPage,
    OpportunityResponse,
    SaveResponse,
)
from app.modules.recruitment.service import (
    RecruitmentError,
    application_appeal_response,
    create_application,
    create_application_appeal,
    get_application_deadline_calendar,
    get_opportunity,
    get_student_application,
    list_opportunities,
    list_student_applications,
    response_for_application,
    toggle_saved,
    withdraw_application,
)

router = APIRouter(dependencies=[Depends(require_roles(UserRole.STUDENT.value))])


def _http_error(error: RecruitmentError) -> HTTPException:
    code = str(error)
    if code.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in {
        "application_already_exists",
        "application_appeal_already_open",
        "application_appeal_not_permitted",
        "application_withdrawal_deadline_passed",
        "application_withdrawal_not_permitted",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)


@router.get("/opportunities", response_model=OpportunityPage)
async def read_opportunities(
    db: Database,
    tenant: CurrentTenant,
    q: Annotated[str | None, Query(max_length=120)] = None,
    location: Annotated[str | None, Query(max_length=120)] = None,
    work_mode: Annotated[str | None, Query(pattern=r"^(on-site|hybrid|remote)$")] = None,
    skill: Annotated[str | None, Query(max_length=80)] = None,
    eligibility: Annotated[
        str | None,
        Query(pattern=r"^(eligible|ineligible|needs_manual_review|unavailable)$"),
    ] = None,
    application_state: Annotated[
        str | None,
        Query(
            pattern=r"^(submitted|under_review|shortlisted|interview|offered|rejected|withdrawn)$"
        ),
    ] = None,
    deadline_within_days: Annotated[int | None, Query(ge=1, le=90)] = None,
    saved_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> OpportunityPage:
    return await list_opportunities(
        db,
        tenant.institution_id,
        tenant.user_id,
        query=q,
        location=location,
        work_mode=work_mode,
        skill=skill,
        saved_only=saved_only,
        page=page,
        page_size=page_size,
        eligibility_status=eligibility,
        application_status=application_state,
        deadline_within_days=deadline_within_days,
    )


@router.get("/opportunities/{role_id}", response_model=OpportunityResponse)
async def read_opportunity(
    role_id: UUID, db: Database, tenant: CurrentTenant
) -> OpportunityResponse:
    try:
        return await get_opportunity(db, tenant.institution_id, tenant.user_id, role_id)
    except RecruitmentError as error:
        raise _http_error(error) from error


@router.post(
    "/opportunities/{role_id}/save",
    response_model=SaveResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def save_opportunity(role_id: UUID, db: Database, tenant: CurrentTenant) -> SaveResponse:
    try:
        saved = await toggle_saved(db, tenant.institution_id, tenant.user_id, role_id)
    except RecruitmentError as error:
        raise _http_error(error) from error
    await db.commit()
    return SaveResponse(role_id=role_id, saved=saved)


@router.get("/applications", response_model=list[ApplicationResponse])
async def read_student_applications(
    db: Database, tenant: CurrentTenant
) -> list[ApplicationResponse]:
    return await list_student_applications(db, tenant.institution_id, tenant.user_id)


@router.get("/applications/{application_id}", response_model=ApplicationResponse)
async def read_student_application(
    application_id: UUID, db: Database, tenant: CurrentTenant
) -> ApplicationResponse:
    try:
        return await get_student_application(
            db, tenant.institution_id, tenant.user_id, application_id
        )
    except RecruitmentError as error:
        raise _http_error(error) from error


@router.post(
    "/applications/{application_id}/withdraw",
    response_model=ApplicationResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def withdraw_student_application(
    request: Request,
    application_id: UUID,
    payload: ApplicationWithdrawal,
    db: Database,
    tenant: CurrentTenant,
) -> ApplicationResponse:
    try:
        application, replayed = await withdraw_application(
            db, tenant.institution_id, tenant.user_id, application_id, payload
        )
        response = await response_for_application(db, application)
    except RecruitmentError as error:
        raise _http_error(error) from error
    if not replayed:
        record_audit_event(
            db,
            event_type="application.withdrawn",
            actor_user_id=tenant.user_id,
            institution_id=tenant.institution_id,
            resource_type="application",
            resource_id=str(application.id),
            correlation_id=request.state.correlation_id,
            details={"reason_recorded": True},
        )
        await db.commit()
    return response


@router.post(
    "/applications/{application_id}/appeals",
    response_model=ApplicationAppealResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def submit_application_appeal(
    request: Request,
    application_id: UUID,
    payload: ApplicationAppealCreate,
    db: Database,
    tenant: CurrentTenant,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)],
) -> ApplicationAppealResponse | JSONResponse:
    try:
        appeal, replayed = await create_application_appeal(
            db,
            tenant.institution_id,
            tenant.user_id,
            application_id,
            idempotency_key,
            payload,
        )
        response = application_appeal_response(appeal)
    except RecruitmentError as error:
        raise _http_error(error) from error
    if not replayed:
        record_audit_event(
            db,
            event_type="application.appeal_submitted",
            actor_user_id=tenant.user_id,
            institution_id=tenant.institution_id,
            resource_type="application_appeal",
            resource_id=str(appeal.id),
            correlation_id=request.state.correlation_id,
            details={"application_id": str(application_id), "kind": appeal.kind},
        )
        await db.commit()
    if replayed:
        return JSONResponse(response.model_dump(mode="json"), status_code=status.HTTP_200_OK)
    return response


@router.get("/applications/{application_id}/deadline.ics")
async def download_application_deadline(
    application_id: UUID, db: Database, tenant: CurrentTenant
) -> Response:
    try:
        calendar = await get_application_deadline_calendar(
            db, tenant.institution_id, tenant.user_id, application_id
        )
    except RecruitmentError as error:
        raise _http_error(error) from error
    return Response(
        content=calendar,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="application-{application_id}-deadline.ics"'
            ),
            "Cache-Control": "private, no-store",
        },
    )


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
    tenant: CurrentTenant,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)],
) -> ApplicationResponse | JSONResponse:
    try:
        application, replayed = await create_application(
            db,
            tenant.institution_id,
            tenant.user_id,
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
            actor_user_id=tenant.user_id,
            institution_id=tenant.institution_id,
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
