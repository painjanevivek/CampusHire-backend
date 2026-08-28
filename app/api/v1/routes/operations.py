from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_permissions,
    verify_authenticated_csrf,
)
from app.modules.operations.schemas import (
    OperationsSummaryResponse,
    ResumeJobOperatorResponse,
    ResumeJobPage,
)
from app.modules.operations.service import (
    OperationsError,
    cancel_resume_job,
    list_resume_jobs,
    operations_summary,
    retry_resume_job,
)

router = APIRouter(
    prefix="/admin/operations",
    dependencies=[Depends(require_permissions("operations.read"))],
)


def _institution(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active institution membership is required",
        )
    return principal.institution_id


def _error(error: OperationsError) -> HTTPException:
    code = str(error)
    if code.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)


@router.get("/resume-jobs", response_model=ResumeJobPage)
async def read_resume_jobs(
    db: Database,
    principal: CurrentPrincipal,
    job_status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ResumeJobPage:
    try:
        return await list_resume_jobs(
            db, _institution(principal), status_filter=job_status, limit=limit
        )
    except OperationsError as error:
        raise _error(error) from error


@router.get("/summary", response_model=OperationsSummaryResponse)
async def read_operations_summary(
    db: Database, principal: CurrentPrincipal
) -> OperationsSummaryResponse:
    return await operations_summary(db, _institution(principal))


@router.post(
    "/resume-jobs/{job_id}/cancel",
    response_model=ResumeJobOperatorResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("operations.manage")),
    ],
)
async def cancel_job(
    request: Request, job_id: UUID, db: Database, principal: CurrentPrincipal
) -> ResumeJobOperatorResponse:
    try:
        response = await cancel_resume_job(
            db,
            _institution(principal),
            job_id,
            correlation_id=request.state.correlation_id,
        )
    except OperationsError as error:
        raise _error(error) from error
    record_audit_event(
        db,
        event_type="resume_job.cancellation_requested",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_processing_job",
        resource_id=str(job_id),
        correlation_id=request.state.correlation_id,
        details={"status": response.status},
    )
    await db.commit()
    return response


@router.post(
    "/resume-jobs/{job_id}/retry",
    response_model=ResumeJobOperatorResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("operations.manage")),
    ],
)
async def retry_job(
    request: Request, job_id: UUID, db: Database, principal: CurrentPrincipal
) -> ResumeJobOperatorResponse:
    try:
        response = await retry_resume_job(
            db,
            _institution(principal),
            job_id,
            correlation_id=request.state.correlation_id,
        )
    except OperationsError as error:
        raise _error(error) from error
    record_audit_event(
        db,
        event_type="resume_job.retry_requested",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_processing_job",
        resource_id=str(job_id),
        correlation_id=request.state.correlation_id,
        details={"status": response.status},
    )
    await db.commit()
    return response
