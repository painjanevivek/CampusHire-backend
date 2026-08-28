from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth import UserRole
from app.models.recruitment import Application
from app.models.resume import ScanStatus
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.resumes.builder import ResumeContent
from app.modules.resumes.parser import InvalidResumeError
from app.modules.resumes.schemas import (
    ExtractionReviewRequest,
    ResumeUploadResponse,
    ResumeVersionResponse,
    SuggestionDecisionRequest,
    SuggestionReviewBatch,
)
from app.modules.resumes.service import validate_upload_envelope
from app.modules.resumes.storage import LocalObjectStore, ObjectStoreError
from app.modules.resumes.workflow import (
    ResumeWorkflowError,
    create_generated_version,
    create_uploaded_version,
    decide_suggestion,
    delete_owned_version,
    get_owned_version,
    list_owned_versions,
    retry_job,
    review_extraction,
    review_suggestions_batch,
    to_response,
)

router = APIRouter(prefix="/resumes", dependencies=[Depends(require_roles(UserRole.STUDENT.value))])


def _store() -> LocalObjectStore:
    return LocalObjectStore(get_settings().resume_storage_path)


def _workflow_http_error(error: ResumeWorkflowError) -> HTTPException:
    code = str(error)
    if code in {"resume_not_found", "resume_suggestion_not_found"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in {
        "resume_invalid_field_decision",
        "resume_suggestion_unsupported_claim",
        "resume_extraction_unavailable",
    }:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)


@router.get("", response_model=list[ResumeVersionResponse])
async def list_resumes(db: Database, principal: CurrentPrincipal) -> list[ResumeVersionResponse]:
    versions = await list_owned_versions(db, principal.user.id)
    version_ids = [version.id for version in versions]
    locked_ids = (
        set(
            (
                await db.scalars(
                    select(Application.resume_version_id).where(
                        Application.resume_version_id.in_(version_ids)
                    )
                )
            ).all()
        )
        if version_ids
        else set()
    )
    return [
        to_response(version).model_copy(update={"locked_by_application": version.id in locked_ids})
        for version in versions
    ]


@router.post(
    "",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def upload_resume(
    request: Request,
    file: Annotated[UploadFile, File()],
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeUploadResponse:
    settings = get_settings()
    data = await file.read(settings.resume_max_bytes + 1)
    try:
        validate_upload_envelope(data, file.content_type or "", settings.resume_max_bytes)
        result = await create_uploaded_version(
            db,
            user_id=principal.user.id,
            institution_id=principal.institution_id,
            data=data,
            filename=file.filename or "resume.pdf",
            content_type=file.content_type or "application/pdf",
            store=_store(),
            settings=settings,
        )
    except InvalidResumeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.uploaded",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(result.id),
        correlation_id=request.state.correlation_id,
        details={"duplicate": result.duplicate, "version_number": result.version_number},
    )
    await db.commit()
    return result


@router.post(
    "/generate",
    response_model=ResumeVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def generate_resume_version(
    request: Request,
    payload: ResumeContent,
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeVersionResponse:
    try:
        version = await create_generated_version(
            db,
            user_id=principal.user.id,
            institution_id=principal.institution_id,
            content=payload,
            store=_store(),
            settings=get_settings(),
        )
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.generated",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(version.id),
        correlation_id=request.state.correlation_id,
        details={"version_number": version.version_number},
    )
    await db.commit()
    return to_response(version)


@router.get("/{resume_id}", response_model=ResumeVersionResponse)
async def read_resume(
    resume_id: UUID, db: Database, principal: CurrentPrincipal
) -> ResumeVersionResponse:
    try:
        return to_response(await get_owned_version(db, principal.user.id, resume_id))
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error


@router.post(
    "/{resume_id}/review",
    response_model=ResumeVersionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def review_resume_extraction(
    request: Request,
    resume_id: UUID,
    payload: ExtractionReviewRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeVersionResponse:
    try:
        version = await review_extraction(
            db, user_id=principal.user.id, version_id=resume_id, payload=payload
        )
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.extraction_reviewed",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(resume_id),
        correlation_id=request.state.correlation_id,
        details={"decision_count": len(payload.decisions)},
    )
    await db.commit()
    return to_response(version)


@router.post(
    "/{resume_id}/suggestions/{suggestion_id}",
    response_model=ResumeVersionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def review_resume_suggestion(
    request: Request,
    resume_id: UUID,
    suggestion_id: UUID,
    payload: SuggestionDecisionRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeVersionResponse:
    try:
        version = await decide_suggestion(
            db,
            user_id=principal.user.id,
            version_id=resume_id,
            suggestion_id=suggestion_id,
            payload=payload,
        )
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.suggestion_decided",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(resume_id),
        correlation_id=request.state.correlation_id,
        details={"suggestion_id": str(suggestion_id), "decision": payload.action},
    )
    await db.commit()
    return to_response(version)


@router.post(
    "/{resume_id}/suggestion-review",
    response_model=ResumeVersionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def review_resume_suggestions(
    request: Request,
    resume_id: UUID,
    payload: SuggestionReviewBatch,
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeVersionResponse:
    try:
        version = await review_suggestions_batch(
            db, user_id=principal.user.id, version_id=resume_id, payload=payload
        )
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.suggestions_reviewed",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(resume_id),
        correlation_id=request.state.correlation_id,
        details={"decision_count": len(payload.decisions)},
    )
    await db.commit()
    return to_response(version)


@router.post(
    "/{resume_id}/retry",
    response_model=ResumeVersionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def retry_resume_job(
    resume_id: UUID, db: Database, principal: CurrentPrincipal
) -> ResumeVersionResponse:
    try:
        return to_response(await retry_job(db, user_id=principal.user.id, version_id=resume_id))
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error


@router.delete(
    "/{resume_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def delete_resume_version(
    request: Request,
    resume_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
) -> None:
    try:
        await delete_owned_version(
            db,
            user_id=principal.user.id,
            version_id=resume_id,
            store=_store(),
        )
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.version_deleted",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(resume_id),
        correlation_id=request.state.correlation_id,
    )
    await db.commit()


@router.get("/{resume_id}/download")
async def download_resume(resume_id: UUID, db: Database, principal: CurrentPrincipal) -> Response:
    try:
        version = await get_owned_version(db, principal.user.id, resume_id)
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    if version.scan_status != ScanStatus.CLEAN.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="resume_not_downloadable")
    try:
        data = _store().read(version.storage_key)
    except ObjectStoreError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="resume_storage_unavailable",
        ) from error
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{version.original_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
