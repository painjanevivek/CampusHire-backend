import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth import UserRole
from app.models.resume import ResumeVersion
from app.modules.auth.dependencies import (
    CurrentUser,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.resumes.builder import ResumeContent, generate_pdf, readiness_score
from app.modules.resumes.service import (
    InvalidResumeError,
    resolve_storage_key,
    sanitize_filename,
    store_pdf,
    validate_pdf,
)

router = APIRouter(prefix="/resumes", dependencies=[Depends(require_roles(UserRole.STUDENT.value))])


@router.post("/generate", dependencies=[Depends(verify_authenticated_csrf)])
async def generate_resume(payload: ResumeContent, user: CurrentUser) -> Response:
    data = generate_pdf(payload)
    score, _ = readiness_score(payload)
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="campushire-{user.id}.pdf"',
            "X-CampusHire-Readiness": str(score),
            "X-CampusHire-Rubric": "resume-readiness-v1",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(verify_authenticated_csrf)]
)
async def upload_resume(
    file: Annotated[UploadFile, File()], db: Database, user: CurrentUser
) -> dict[str, object]:
    settings = get_settings()
    data = await file.read(settings.resume_max_bytes + 1)
    try:
        parsed = validate_pdf(
            data, file.content_type or "", settings.resume_max_bytes, settings.resume_max_pages
        )
        checksum = hashlib.sha256(data).hexdigest()
    except InvalidResumeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    existing = await db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.user_id == user.id, ResumeVersion.checksum == checksum
        )
    )
    if existing:
        return {"id": str(existing.id), "status": existing.status, "duplicate": True}
    key = store_pdf(data, settings.resume_storage_path)
    version = ResumeVersion(
        user_id=user.id,
        storage_key=key,
        original_name=sanitize_filename(file.filename or "resume.pdf"),
        checksum=checksum,
        status="completed",
        page_count=parsed.page_count,
        extracted_text=parsed.text,
        created_at=datetime.now(UTC),
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return {"id": str(version.id), "status": version.status, "duplicate": False}


@router.get("/{resume_id}/download")
async def download_resume(resume_id: str, db: Database, user: CurrentUser) -> FileResponse:
    version = await db.scalar(
        select(ResumeVersion).where(ResumeVersion.id == resume_id, ResumeVersion.user_id == user.id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return FileResponse(
        resolve_storage_key(get_settings().resume_storage_path, version.storage_key),
        media_type="application/pdf",
        filename=version.original_name,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )
