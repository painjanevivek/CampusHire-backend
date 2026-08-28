import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.models.recruitment import Application
from app.models.resume import (
    JobStatus,
    Resume,
    ResumeProcessingJob,
    ResumeSource,
    ResumeStatus,
    ResumeVersion,
    ScanStatus,
    SuggestionStatus,
)
from app.modules.resumes.builder import ResumeContent, generate_pdf, suggestion_is_supported
from app.modules.resumes.pipeline import RETRYABLE_ERRORS, record_job_event
from app.modules.resumes.schemas import (
    ExtractionReviewRequest,
    ResumeJobResponse,
    ResumeSuggestionResponse,
    ResumeUploadResponse,
    ResumeVersionResponse,
    SuggestionDecisionRequest,
    SuggestionReviewBatch,
)
from app.modules.resumes.service import sanitize_filename
from app.modules.resumes.storage import ObjectStore, ObjectStoreError


class ResumeWorkflowError(RuntimeError):
    pass


async def _container(db: AsyncSession, user_id: UUID, institution_id: UUID | None) -> Resume:
    resume = await db.scalar(select(Resume).where(Resume.user_id == user_id).with_for_update())
    if resume is None:
        resume = Resume(user_id=user_id, institution_id=institution_id)
        db.add(resume)
        await db.flush()
    elif resume.institution_id is None and institution_id is not None:
        resume.institution_id = institution_id
    return resume


async def _next_version_number(
    db: AsyncSession, user_id: UUID, institution_id: UUID | None, max_versions: int
) -> tuple[Resume, int]:
    count = await db.scalar(
        select(func.count()).select_from(ResumeVersion).where(ResumeVersion.user_id == user_id)
    )
    if (count or 0) >= max_versions:
        raise ResumeWorkflowError("resume_version_limit")
    resume = await _container(db, user_id, institution_id)
    resume.latest_version_number += 1
    return resume, resume.latest_version_number


def _job_response(job: ResumeProcessingJob | None) -> ResumeJobResponse | None:
    if job is None:
        return None
    return ResumeJobResponse(
        id=job.id,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        safe_error_code=job.safe_error_code,
        retryable=bool(job.safe_error_code in RETRYABLE_ERRORS and job.attempts < job.max_attempts),
        cancellable=job.status
        in {
            JobStatus.QUEUED.value,
            JobStatus.PROCESSING.value,
            JobStatus.CANCELLATION_REQUESTED.value,
            JobStatus.FAILED.value,
        },
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=job.duration_ms,
    )


def to_response(version: ResumeVersion) -> ResumeVersionResponse:
    return ResumeVersionResponse(
        id=version.id,
        version_number=version.version_number,
        source=version.source,
        original_name=version.original_name,
        status=version.status,
        scan_status=version.scan_status,
        page_count=version.page_count,
        created_at=version.created_at,
        review_completed_at=version.review_completed_at,
        safe_error_code=version.safe_error_code,
        extracted_data=version.extracted_data,
        job=_job_response(version.processing_job),
        suggestions=[
            ResumeSuggestionResponse(
                id=item.id,
                field_path=item.field_path,
                original_text=item.original_text,
                proposed_text=item.proposed_text,
                rationale=item.rationale,
                status=item.status,
                decided_text=item.decided_text,
            )
            for item in sorted(version.suggestions, key=lambda value: value.created_at)
        ],
    )


async def create_uploaded_version(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution_id: UUID | None,
    data: bytes,
    filename: str,
    content_type: str,
    store: ObjectStore,
    settings: Settings,
) -> ResumeUploadResponse:
    checksum = hashlib.sha256(data).hexdigest()
    existing = await db.scalar(
        select(ResumeVersion)
        .options(selectinload(ResumeVersion.processing_job))
        .where(ResumeVersion.user_id == user_id, ResumeVersion.checksum == checksum)
    )
    if existing:
        return ResumeUploadResponse(
            id=existing.id,
            version_number=existing.version_number,
            status=existing.status,
            scan_status=existing.scan_status,
            duplicate=True,
            job_id=existing.processing_job.id if existing.processing_job else None,
        )
    key = store.put_quarantined(data)
    try:
        resume, version_number = await _next_version_number(
            db, user_id, institution_id, settings.resume_max_versions
        )
        version = ResumeVersion(
            resume_id=resume.id,
            user_id=user_id,
            institution_id=institution_id,
            version_number=version_number,
            source=ResumeSource.UPLOAD.value,
            storage_key=key,
            original_name=sanitize_filename(filename),
            checksum=checksum,
            content_type=content_type,
            size_bytes=len(data),
            status=ResumeStatus.QUEUED.value,
            scan_status=ScanStatus.QUARANTINED.value,
            created_at=datetime.now(UTC),
        )
        db.add(version)
        await db.flush()
        job = ResumeProcessingJob(
            resume_version_id=version.id,
            max_attempts=settings.resume_job_max_attempts,
        )
        db.add(job)
        await db.flush()
        record_job_event(db, job, "queued")
        await db.commit()
        await db.refresh(job)
    except Exception:
        await db.rollback()
        store.delete(key)
        raise
    return ResumeUploadResponse(
        id=version.id,
        version_number=version.version_number,
        status=version.status,
        scan_status=version.scan_status,
        duplicate=False,
        job_id=job.id,
    )


async def create_generated_version(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution_id: UUID | None,
    content: ResumeContent,
    store: ObjectStore,
    settings: Settings,
) -> ResumeVersion:
    data = generate_pdf(content)
    checksum = hashlib.sha256(data).hexdigest()
    existing = await get_owned_version_by_checksum(db, user_id, checksum)
    if existing is not None:
        return existing
    quarantine_key = store.put_quarantined(data)
    clean_key: str | None = None
    try:
        clean_key = store.promote_clean(quarantine_key)
        resume, version_number = await _next_version_number(
            db, user_id, institution_id, settings.resume_max_versions
        )
        version = ResumeVersion(
            resume_id=resume.id,
            user_id=user_id,
            institution_id=institution_id,
            version_number=version_number,
            source=ResumeSource.GENERATED.value,
            storage_key=clean_key,
            original_name=f"campushire-resume-v{version_number}.pdf",
            checksum=checksum,
            content_type="application/pdf",
            size_bytes=len(data),
            status=ResumeStatus.COMPLETED.value,
            scan_status=ScanStatus.CLEAN.value,
            scan_engine="campushire-generator-v1",
            scanned_at=datetime.now(UTC),
            extracted_data={"accepted": content.model_dump(mode="json")},
            review_completed_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        db.add(version)
        await db.commit()
        return await get_owned_version(db, user_id, version.id)
    except Exception:
        await db.rollback()
        store.delete(quarantine_key)
        if clean_key is not None:
            store.delete(clean_key)
        raise


async def get_owned_version_by_checksum(
    db: AsyncSession, user_id: UUID, checksum: str
) -> ResumeVersion | None:
    version: ResumeVersion | None = await db.scalar(
        select(ResumeVersion)
        .options(
            selectinload(ResumeVersion.processing_job), selectinload(ResumeVersion.suggestions)
        )
        .execution_options(populate_existing=True)
        .where(ResumeVersion.user_id == user_id, ResumeVersion.checksum == checksum)
    )
    return version


async def get_owned_version(db: AsyncSession, user_id: UUID, version_id: UUID) -> ResumeVersion:
    version = await db.scalar(
        select(ResumeVersion)
        .options(
            selectinload(ResumeVersion.processing_job), selectinload(ResumeVersion.suggestions)
        )
        .execution_options(populate_existing=True)
        .where(ResumeVersion.id == version_id, ResumeVersion.user_id == user_id)
    )
    if version is None:
        raise ResumeWorkflowError("resume_not_found")
    return version


async def list_owned_versions(db: AsyncSession, user_id: UUID) -> list[ResumeVersion]:
    return list(
        (
            await db.scalars(
                select(ResumeVersion)
                .options(
                    selectinload(ResumeVersion.processing_job),
                    selectinload(ResumeVersion.suggestions),
                )
                .execution_options(populate_existing=True)
                .where(ResumeVersion.user_id == user_id)
                .order_by(ResumeVersion.created_at.desc())
            )
        ).all()
    )


def _finish_review_if_complete(version: ResumeVersion) -> None:
    proposed = version.extracted_data.get("proposed", {})
    decisions = version.extracted_data.get("decisions", {})
    extraction_complete = (
        isinstance(proposed, dict)
        and isinstance(decisions, dict)
        and set(proposed).issubset(decisions)
    )
    suggestions_complete = all(
        suggestion.status != SuggestionStatus.PENDING.value for suggestion in version.suggestions
    )
    if extraction_complete and suggestions_complete:
        version.status = ResumeStatus.COMPLETED.value
        version.review_completed_at = datetime.now(UTC)


async def review_extraction(
    db: AsyncSession,
    *,
    user_id: UUID,
    version_id: UUID,
    payload: ExtractionReviewRequest,
) -> ResumeVersion:
    version = await get_owned_version(db, user_id, version_id)
    if version.status != ResumeStatus.REVIEW_REQUIRED.value:
        raise ResumeWorkflowError("resume_not_ready_for_review")
    proposed = version.extracted_data.get("proposed", {})
    current = dict(version.extracted_data.get("decisions", {}))
    if not isinstance(proposed, dict):
        raise ResumeWorkflowError("resume_extraction_unavailable")
    seen: set[str] = set()
    for decision in payload.decisions:
        if decision.field_path in seen or decision.field_path not in proposed:
            raise ResumeWorkflowError("resume_invalid_field_decision")
        seen.add(decision.field_path)
        value = decision.value if decision.action == "edit" else proposed[decision.field_path]
        current[decision.field_path] = {"action": decision.action, "value": value}
    version.extracted_data = {**version.extracted_data, "decisions": current}
    _finish_review_if_complete(version)
    await db.commit()
    return await get_owned_version(db, user_id, version_id)


async def decide_suggestion(
    db: AsyncSession,
    *,
    user_id: UUID,
    version_id: UUID,
    suggestion_id: UUID,
    payload: SuggestionDecisionRequest,
) -> ResumeVersion:
    version = await get_owned_version(db, user_id, version_id)
    suggestion = next((item for item in version.suggestions if item.id == suggestion_id), None)
    if suggestion is None:
        raise ResumeWorkflowError("resume_suggestion_not_found")
    if suggestion.status != SuggestionStatus.PENDING.value:
        raise ResumeWorkflowError("resume_suggestion_already_decided")
    if payload.action == "edit":
        assert payload.edited_text is not None
        known_facts = {
            term
            for term in ("increased", "reduced", "million", "award", "certified")
            if term in (version.extracted_text or "").casefold()
        }
        if not suggestion_is_supported(payload.edited_text, known_facts):
            raise ResumeWorkflowError("resume_suggestion_unsupported_claim")
        suggestion.status = SuggestionStatus.EDITED.value
        suggestion.decided_text = payload.edited_text
    elif payload.action == "accept":
        suggestion.status = SuggestionStatus.ACCEPTED.value
        suggestion.decided_text = suggestion.proposed_text
    else:
        suggestion.status = SuggestionStatus.REJECTED.value
        suggestion.decided_text = None
    suggestion.decided_at = datetime.now(UTC)
    _finish_review_if_complete(version)
    await db.commit()
    return await get_owned_version(db, user_id, version_id)


async def review_suggestions_batch(
    db: AsyncSession,
    *,
    user_id: UUID,
    version_id: UUID,
    payload: SuggestionReviewBatch,
) -> ResumeVersion:
    version = await get_owned_version(db, user_id, version_id)
    if version.status != ResumeStatus.REVIEW_REQUIRED.value:
        raise ResumeWorkflowError("resume_not_ready_for_review")
    suggestions = {item.id: item for item in version.suggestions}
    for decision in payload.decisions:
        suggestion = suggestions.get(decision.suggestion_id)
        if suggestion is None:
            raise ResumeWorkflowError("resume_suggestion_not_found")
        if suggestion.status != SuggestionStatus.PENDING.value:
            raise ResumeWorkflowError("resume_suggestion_already_decided")
        if decision.action == "edit":
            assert decision.edited_text is not None
            known_facts = {
                term
                for term in ("increased", "reduced", "million", "award", "certified")
                if term in (version.extracted_text or "").casefold()
            }
            if not suggestion_is_supported(decision.edited_text, known_facts):
                raise ResumeWorkflowError("resume_suggestion_unsupported_claim")

    now = datetime.now(UTC)
    for decision in payload.decisions:
        suggestion = suggestions[decision.suggestion_id]
        if decision.action == "edit":
            suggestion.status = SuggestionStatus.EDITED.value
            suggestion.decided_text = decision.edited_text
        elif decision.action == "accept":
            suggestion.status = SuggestionStatus.ACCEPTED.value
            suggestion.decided_text = suggestion.proposed_text
        else:
            suggestion.status = SuggestionStatus.REJECTED.value
            suggestion.decided_text = None
        suggestion.decided_at = now
    _finish_review_if_complete(version)
    await db.commit()
    return await get_owned_version(db, user_id, version_id)


async def delete_owned_version(
    db: AsyncSession,
    *,
    user_id: UUID,
    version_id: UUID,
    store: ObjectStore,
) -> None:
    version = await get_owned_version(db, user_id, version_id)
    application_id = await db.scalar(
        select(Application.id).where(Application.resume_version_id == version.id).limit(1)
    )
    if application_id is not None:
        raise ResumeWorkflowError("resume_version_locked_by_application")
    if version.status in {ResumeStatus.QUEUED.value, ResumeStatus.PROCESSING.value}:
        raise ResumeWorkflowError("resume_processing_in_progress")
    storage_key = version.storage_key
    await db.delete(version)
    await db.flush()
    try:
        store.delete(storage_key)
    except ObjectStoreError as error:
        await db.rollback()
        raise ResumeWorkflowError("resume_storage_unavailable") from error
    await db.commit()


async def retry_job(db: AsyncSession, *, user_id: UUID, version_id: UUID) -> ResumeVersion:
    version = await get_owned_version(db, user_id, version_id)
    job = version.processing_job
    if (
        job is None
        or job.status != JobStatus.FAILED.value
        or job.safe_error_code not in RETRYABLE_ERRORS
        or job.attempts >= job.max_attempts
    ):
        raise ResumeWorkflowError("resume_job_not_retryable")
    job.status = JobStatus.QUEUED.value
    job.available_at = datetime.now(UTC)
    job.finished_at = None
    job.duration_ms = None
    job.cancellation_requested_at = None
    job.claimed_by = None
    job.lease_expires_at = None
    version.status = ResumeStatus.QUEUED.value
    version.safe_error_code = None
    record_job_event(db, job, "student_retry_queued")
    await db.commit()
    return await get_owned_version(db, user_id, version_id)
