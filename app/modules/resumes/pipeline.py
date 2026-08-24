import logging
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.models.resume import (
    JobStatus,
    ResumeJobEvent,
    ResumeProcessingJob,
    ResumeStatus,
    ResumeSuggestion,
    ResumeVersion,
    ScanStatus,
)
from app.modules.resumes.parser import (
    InvalidResumeError,
    ParserUnavailableError,
    PdfParser,
    build_pdf_parser,
)
from app.modules.resumes.scanner import MalwareScanner, ScannerUnavailableError
from app.modules.resumes.storage import ObjectStore, ObjectStoreError

RETRYABLE_ERRORS = {
    "resume_scan_unavailable",
    "resume_parser_timeout",
    "resume_parser_unavailable",
    "resume_storage_unavailable",
    "resume_worker_interrupted",
}
logger = logging.getLogger(__name__)
SKILLS = (
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "React",
    "Next.js",
    "FastAPI",
    "SQL",
    "PostgreSQL",
    "Machine Learning",
)


def extract_structured_data(text: str) -> dict[str, object]:
    lines = [line.strip() for line in text.splitlines() if line.strip()][:400]
    proposed: dict[str, object] = {}
    email = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.IGNORECASE)
    urls = re.findall(r"https://[^\s<>]+", text)
    if lines and len(lines[0]) <= 100 and not re.search(r"[@\d]", lines[0]):
        proposed["full_name"] = lines[0]
    if email:
        proposed["email"] = email.group(0)
    if urls:
        proposed["links"] = urls[:5]
    matched_skills = [
        skill for skill in SKILLS if re.search(rf"\b{re.escape(skill)}\b", text, re.I)
    ]
    if matched_skills:
        proposed["skills"] = matched_skills
    education = [
        line
        for line in lines
        if re.search(r"\b(B\.?Tech|Bachelor|BSc|M\.?Tech|Master|University|College)\b", line, re.I)
    ]
    if education:
        proposed["education"] = education[:6]
    projects = [
        line
        for line in lines
        if re.search(r"\b(project|built|developed|implemented|worked on|contributed)\b", line, re.I)
    ]
    if projects:
        proposed["projects"] = projects[:10]
    return {"proposed": proposed, "decisions": {}}


def build_safe_suggestions(text: str) -> list[tuple[str, str, str, str]]:
    suggestions: list[tuple[str, str, str, str]] = []
    for index, match in enumerate(re.finditer(r"(?im)^Worked on\s+(.+?)[.]?$", text)):
        subject = match.group(1).strip()
        suggestions.append(
            (
                f"projects.{index}",
                match.group(0).strip(),
                f"Contributed to {subject.rstrip('.')}.",
                "Uses a specific contribution verb without adding an outcome or metric.",
            )
        )
    return suggestions[:10]


def record_job_event(
    db: AsyncSession,
    job: ResumeProcessingJob,
    event_type: str,
    *,
    worker_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    db.add(
        ResumeJobEvent(
            job_id=job.id,
            event_type=event_type,
            status=job.status,
            attempt=job.attempts,
            worker_id=worker_id or job.claimed_by,
            safe_error_code=job.safe_error_code,
            correlation_id=correlation_id,
        )
    )


def _duration_ms(job: ResumeProcessingJob, finished_at: datetime) -> int | None:
    if job.started_at is None:
        return None
    started_at = job.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    return max(0, int((finished_at - started_at).total_seconds() * 1_000))


async def _cancel_job(
    db: AsyncSession,
    job: ResumeProcessingJob,
    *,
    event_type: str,
    correlation_id: str | None = None,
) -> None:
    now = datetime.now(UTC)
    job.status = JobStatus.CANCELLED.value
    job.resume_version.status = ResumeStatus.CANCELLED.value
    job.safe_error_code = "resume_job_cancelled"
    job.resume_version.safe_error_code = "resume_job_cancelled"
    job.finished_at = now
    job.duration_ms = _duration_ms(job, now)
    job.claimed_by = None
    job.lease_expires_at = None
    record_job_event(db, job, event_type, correlation_id=correlation_id)
    await db.commit()


async def claim_next_job(
    db: AsyncSession,
    *,
    worker_id: str = "inline-worker",
    lease_seconds: int = 300,
) -> UUID | None:
    now = datetime.now(UTC)
    job = await db.scalar(
        select(ResumeProcessingJob)
        .where(
            ResumeProcessingJob.status == JobStatus.QUEUED.value,
            ResumeProcessingJob.available_at <= now,
        )
        .order_by(ResumeProcessingJob.available_at, ResumeProcessingJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = JobStatus.PROCESSING.value
    job.attempts += 1
    job.started_at = now
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.claimed_by = worker_id
    job.safe_error_code = None
    record_job_event(db, job, "claimed", worker_id=worker_id)
    await db.commit()
    return job.id


async def recover_stale_jobs(db: AsyncSession, *, stale_after_seconds: int = 300) -> int:
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=stale_after_seconds)
    jobs = list(
        (
            await db.scalars(
                select(ResumeProcessingJob)
                .options(selectinload(ResumeProcessingJob.resume_version))
                .where(
                    ResumeProcessingJob.status.in_(
                        (
                            JobStatus.PROCESSING.value,
                            JobStatus.CANCELLATION_REQUESTED.value,
                        )
                    ),
                    or_(
                        ResumeProcessingJob.lease_expires_at < now,
                        ResumeProcessingJob.heartbeat_at < cutoff,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for job in jobs:
        if job.status == JobStatus.CANCELLATION_REQUESTED.value:
            await _cancel_job(db, job, event_type="cancelled_after_stale_lease")
            continue
        job.claimed_by = None
        job.lease_expires_at = None
        if job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED.value
            job.safe_error_code = "resume_worker_interrupted"
            job.available_at = now
            job.resume_version.status = ResumeStatus.QUEUED.value
            job.resume_version.safe_error_code = "resume_worker_interrupted"
            record_job_event(db, job, "stale_lease_requeued")
        else:
            job.status = JobStatus.FAILED.value
            job.safe_error_code = "resume_worker_attempts_exhausted"
            job.finished_at = now
            job.duration_ms = _duration_ms(job, now)
            job.resume_version.status = ResumeStatus.FAILED.value
            job.resume_version.safe_error_code = "resume_worker_attempts_exhausted"
            record_job_event(db, job, "stale_lease_failed")
    if jobs:
        await db.commit()
    return len(jobs)


async def process_job(
    db: AsyncSession,
    job_id: UUID,
    *,
    store: ObjectStore,
    scanner: MalwareScanner,
    settings: Settings,
    parser: PdfParser | None = None,
    correlation_id: str | None = None,
) -> None:
    job = await db.scalar(
        select(ResumeProcessingJob)
        .options(
            selectinload(ResumeProcessingJob.resume_version)
            .selectinload(ResumeVersion.suggestions),
            selectinload(ResumeProcessingJob.events),
        )
        .where(ResumeProcessingJob.id == job_id)
    )
    if job is None or job.status in {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }:
        return
    version = job.resume_version
    if job.status == JobStatus.CANCELLATION_REQUESTED.value:
        await _cancel_job(
            db, job, event_type="cancelled_before_processing", correlation_id=correlation_id
        )
        return
    if job.status != JobStatus.PROCESSING.value:
        now = datetime.now(UTC)
        job.status = JobStatus.PROCESSING.value
        job.attempts += 1
        job.started_at = now
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.resume_worker_lease_seconds)
        record_job_event(db, job, "processing_started", correlation_id=correlation_id)
        await db.commit()
    version.status = ResumeStatus.PROCESSING.value
    await db.commit()

    try:
        data = store.read(version.storage_key)
        now = datetime.now(UTC)
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.resume_worker_lease_seconds)
        await db.commit()
        scan = await scanner.scan(data)
        await db.refresh(job)
        if job.status == JobStatus.CANCELLATION_REQUESTED.value:
            await _cancel_job(
                db, job, event_type="cancelled_after_scan", correlation_id=correlation_id
            )
            return
        version.scan_engine = scan.engine
        version.scanned_at = datetime.now(UTC)
        if not scan.clean:
            version.scan_status = ScanStatus.INFECTED.value
            raise InvalidResumeError("resume_malware_detected")
        version.scan_status = ScanStatus.CLEAN.value
        parser_backend = parser or build_pdf_parser(settings)
        parsed = parser_backend.parse(
            data,
            max_bytes=settings.resume_max_bytes,
            max_pages=settings.resume_max_pages,
        )
        if version.storage_key.startswith("quarantine/"):
            version.storage_key = store.promote_clean(version.storage_key)
        version.page_count = parsed.page_count
        version.extracted_text = parsed.text
        version.extracted_data = extract_structured_data(parsed.text)
        for field_path, original, proposed, rationale in build_safe_suggestions(parsed.text):
            if not any(item.field_path == field_path for item in version.suggestions):
                db.add(
                    ResumeSuggestion(
                        resume_version_id=version.id,
                        field_path=field_path,
                        original_text=original,
                        proposed_text=proposed,
                        rationale=rationale,
                    )
                )
        version.safe_error_code = None
        version.status = (
            ResumeStatus.REVIEW_REQUIRED.value
            if version.extracted_data.get("proposed")
            else ResumeStatus.COMPLETED.value
        )
        if version.status == ResumeStatus.COMPLETED.value:
            version.review_completed_at = datetime.now(UTC)
        finished_at = datetime.now(UTC)
        job.status = JobStatus.COMPLETED.value
        job.finished_at = finished_at
        job.duration_ms = _duration_ms(job, finished_at)
        job.claimed_by = None
        job.lease_expires_at = None
        job.safe_error_code = None
        record_job_event(db, job, "completed", correlation_id=correlation_id)
        await db.commit()
    except (
        InvalidResumeError,
        ObjectStoreError,
        ParserUnavailableError,
        ScannerUnavailableError,
    ) as error:
        code = str(error)
        retryable = code in RETRYABLE_ERRORS and job.attempts < job.max_attempts
        version.safe_error_code = code
        job.safe_error_code = code
        if isinstance(error, ScannerUnavailableError):
            version.scan_status = ScanStatus.FAILED.value
        if retryable:
            job.status = JobStatus.QUEUED.value
            job.available_at = datetime.now(UTC) + timedelta(seconds=min(2**job.attempts, 60))
            job.claimed_by = None
            job.lease_expires_at = None
            version.status = ResumeStatus.QUEUED.value
            record_job_event(db, job, "retry_scheduled", correlation_id=correlation_id)
        else:
            finished_at = datetime.now(UTC)
            job.status = JobStatus.FAILED.value
            job.finished_at = finished_at
            job.duration_ms = _duration_ms(job, finished_at)
            job.claimed_by = None
            job.lease_expires_at = None
            version.status = ResumeStatus.FAILED.value
            record_job_event(db, job, "failed", correlation_id=correlation_id)
        await db.commit()
    except Exception as error:
        finished_at = datetime.now(UTC)
        job.status = JobStatus.FAILED.value
        job.finished_at = finished_at
        job.duration_ms = _duration_ms(job, finished_at)
        job.claimed_by = None
        job.lease_expires_at = None
        job.safe_error_code = "resume_processing_unexpected"
        version.status = ResumeStatus.FAILED.value
        version.safe_error_code = "resume_processing_unexpected"
        record_job_event(db, job, "failed_unexpected", correlation_id=correlation_id)
        await db.commit()
        logger.error(
            "resume_job_unexpected_failure",
            extra={
                "event": "resume_job_unexpected_failure",
                "resource_id": str(job.id),
                "exception_type": type(error).__name__,
            },
        )
