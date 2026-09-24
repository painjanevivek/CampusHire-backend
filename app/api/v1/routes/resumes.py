from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth import UserRole
from app.models.recruitment import Application, PlacementRole
from app.models.resume import ScanStatus
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_student_placement_access,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.communications.service import record_product_event
from app.modules.resumes.builder import ResumeContent
from app.modules.resumes.schemas import (
    ExtractionReviewRequest,
    ResumeRenameRequest,
    ResumeVersionResponse,
    SuggestionDecisionRequest,
    SuggestionReviewBatch,
    TailoredResumeRequest,
)
from app.modules.resumes.storage import ObjectStore, ObjectStoreError, build_object_store
from app.modules.resumes.workflow import (
    ResumeWorkflowError,
    create_generated_version,
    decide_suggestion,
    delete_owned_version,
    get_owned_version,
    list_owned_versions,
    rename_owned_version,
    retry_job,
    review_extraction,
    review_suggestions_batch,
    to_response,
)

router = APIRouter(prefix="/resumes", dependencies=[Depends(require_roles(UserRole.STUDENT.value))])


def _store() -> ObjectStore:
    return build_object_store(get_settings())


def _workflow_http_error(error: ResumeWorkflowError) -> HTTPException:
    code = str(error)
    if code in {"resume_not_found", "resume_suggestion_not_found"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in {
        "resume_invalid_field_decision",
        "resume_invalid_filename",
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
    await record_product_event(
        db,
        event_name="resume_completed",
        route_group="resume",
        institution_id=principal.institution_id,
        dedupe_key=f"resume-completed:{principal.user.id}",
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


@router.patch(
    "/{resume_id}/name",
    response_model=ResumeVersionResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def rename_resume_version(
    request: Request,
    resume_id: UUID,
    payload: ResumeRenameRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeVersionResponse:
    try:
        version = await rename_owned_version(
            db,
            user_id=principal.user.id,
            version_id=resume_id,
            name=payload.name,
        )
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.version_renamed",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(resume_id),
        correlation_id=request.state.correlation_id,
    )
    await db.commit()
    return to_response(version)


@router.get("/{resume_id}/editable-content", response_model=ResumeContent)
async def read_editable_resume_content(
    resume_id: UUID, db: Database, principal: CurrentPrincipal
) -> ResumeContent:
    try:
        version = await get_owned_version(db, principal.user.id, resume_id)
        accepted = version.extracted_data.get("accepted")
        if not isinstance(accepted, dict):
            raise ResumeWorkflowError("resume_not_editable")
        return ResumeContent.model_validate(accepted)
    except (ResumeWorkflowError, ValueError) as error:
        if isinstance(error, ResumeWorkflowError):
            raise _workflow_http_error(error) from error
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="resume_not_editable"
        ) from error


@router.post(
    "/{resume_id}/tailored-versions",
    response_model=ResumeVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf), Depends(require_student_placement_access)],
)
async def create_tailored_resume_version(
    request: Request,
    resume_id: UUID,
    payload: TailoredResumeRequest,
    db: Database,
    principal: CurrentPrincipal,
) -> ResumeVersionResponse:
    try:
        parent = await get_owned_version(db, principal.user.id, resume_id)
        role = await db.scalar(
            select(PlacementRole).where(
                PlacementRole.id == payload.role_id,
                PlacementRole.institution_id == principal.institution_id,
            )
        )
        if role is None:
            raise ResumeWorkflowError("role_not_found")
        version = await create_generated_version(
            db,
            user_id=principal.user.id,
            institution_id=principal.institution_id,
            content=payload.content,
            store=_store(),
            settings=get_settings(),
            parent_version_id=parent.id,
            purpose_role_id=role.id,
        )
    except ResumeWorkflowError as error:
        raise _workflow_http_error(error) from error
    record_audit_event(
        db,
        event_type="resume.tailored",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="resume_version",
        resource_id=str(version.id),
        correlation_id=request.state.correlation_id,
        details={"parent_version_id": str(parent.id), "role_id": str(payload.role_id)},
    )
    await db.commit()
    return to_response(version)


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
