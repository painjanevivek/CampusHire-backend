from typing import Annotated, Literal, NoReturn

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.rate_limit import enforce_fixed_window_limit
from app.models.auth import UserRole
from app.models.onboarding import StudentAcademicDocument
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.onboarding.documents import (
    MAX_ACADEMIC_DOCUMENT_BYTES,
    InvalidAcademicDocument,
    normalize_academic_document,
)
from app.modules.onboarding.schemas import (
    InstitutionOnboardingResponse,
    InstitutionOnboardingUpdate,
    StudentOnboardingResponse,
    StudentOnboardingUpdate,
)
from app.modules.onboarding.service import (
    OnboardingConflictError,
    OnboardingValidationError,
    get_institution_onboarding,
    get_student_onboarding,
    update_institution_onboarding,
    update_student_onboarding,
)
from app.modules.resumes.scanner import ScannerUnavailableError, build_scanner

student_router = APIRouter(
    prefix="/onboarding", dependencies=[Depends(require_roles(UserRole.STUDENT.value))]
)
admin_router = APIRouter(
    prefix="/onboarding",
    dependencies=[Depends(require_roles(UserRole.TNP_OWNER.value))],
)


def _raise_onboarding_error(error: Exception) -> NoReturn:
    if isinstance(error, OnboardingConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "onboarding_revision_conflict",
                "message": "Onboarding changed in another session.",
                "current_revision": error.current_revision,
            },
        ) from error
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": "onboarding_invalid", "message": str(error)},
    ) from error


@student_router.get("", response_model=StudentOnboardingResponse)
async def read_student_onboarding(
    db: Database, principal: CurrentPrincipal
) -> StudentOnboardingResponse:
    return await get_student_onboarding(db, principal.user, principal.institution_id)


@student_router.put(
    "/step",
    response_model=StudentOnboardingResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def save_student_onboarding_step(
    payload: StudentOnboardingUpdate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> StudentOnboardingResponse:
    try:
        return await update_student_onboarding(
            db,
            user=principal.user,
            institution_id=principal.institution_id,
            payload=payload,
            correlation_id=request.state.correlation_id,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        _raise_onboarding_error(error)


AcademicLevel = Literal["class_10", "class_12", "diploma"]


@student_router.get("/academic-documents")
async def list_academic_documents(db: Database, principal: CurrentPrincipal) -> dict[str, bool]:
    from sqlalchemy import select

    levels = await db.scalars(
        select(StudentAcademicDocument.qualification_level).where(
            StudentAcademicDocument.user_id == principal.user.id
        )
    )
    present = set(levels.all())
    return {level: level in present for level in ("class_10", "class_12", "diploma")}


@student_router.put(
    "/academic-documents/{level}",
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def upload_academic_document(
    level: AcademicLevel,
    request: Request,
    file: Annotated[UploadFile, File()],
    db: Database,
    principal: CurrentPrincipal,
) -> dict[str, bool]:
    await enforce_fixed_window_limit(
        request,
        namespace="academic-document",
        identity=str(principal.user.id),
        limit=12,
        unavailable_detail="Academic document uploads are temporarily unavailable.",
    )
    try:
        data = await file.read(MAX_ACADEMIC_DOCUMENT_BYTES + 1)
        content_type, normalized = await run_in_threadpool(
            normalize_academic_document, data, file.content_type or "", file.filename or ""
        )
        scan = await build_scanner(get_settings()).scan(normalized)
        if not scan.clean:
            raise HTTPException(
                status_code=422, detail="The marksheet did not pass the security scan."
            )
    except InvalidAcademicDocument as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ScannerUnavailableError as error:
        raise HTTPException(
            status_code=503, detail="The upload security scan is unavailable."
        ) from error
    finally:
        await file.close()
    document = await db.get(StudentAcademicDocument, (principal.user.id, level))
    if document is None:
        document = StudentAcademicDocument(
            user_id=principal.user.id,
            qualification_level=level,
            content_type=content_type,
            content=normalized,
        )
        db.add(document)
    else:
        document.content_type = content_type
        document.content = normalized
    await db.commit()
    return {"uploaded": True}


@student_router.get("/academic-documents/{level}")
async def download_academic_document(
    level: AcademicLevel, db: Database, principal: CurrentPrincipal
) -> Response:
    document = await db.get(StudentAcademicDocument, (principal.user.id, level))
    if document is None:
        raise HTTPException(status_code=404, detail="Marksheet not found")
    extension = "pdf" if document.content_type == "application/pdf" else "jpg"
    return Response(
        content=document.content,
        media_type=document.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{level}-marksheet.{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@student_router.delete(
    "/academic-documents/{level}",
    status_code=204,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def remove_academic_document(
    level: AcademicLevel, db: Database, principal: CurrentPrincipal
) -> Response:
    document = await db.get(StudentAcademicDocument, (principal.user.id, level))
    if document is not None:
        await db.delete(document)
        await db.commit()
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@admin_router.get("", response_model=InstitutionOnboardingResponse)
async def read_institution_onboarding(
    db: Database, principal: CurrentPrincipal
) -> InstitutionOnboardingResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution membership required")
    try:
        return await get_institution_onboarding(db, principal.institution_id)
    except OnboardingValidationError as error:
        _raise_onboarding_error(error)


@admin_router.put(
    "/step",
    response_model=InstitutionOnboardingResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def save_institution_onboarding_step(
    payload: InstitutionOnboardingUpdate,
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
) -> InstitutionOnboardingResponse:
    if principal.institution_id is None:
        raise HTTPException(status_code=403, detail="Institution membership required")
    try:
        return await update_institution_onboarding(
            db,
            institution_id=principal.institution_id,
            actor_user_id=principal.user.id,
            payload=payload,
            correlation_id=request.state.correlation_id,
        )
    except (OnboardingConflictError, OnboardingValidationError) as error:
        _raise_onboarding_error(error)
