import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.models.resume import (
    JobStatus,
    ResumeProcessingJob,
    ResumeStatus,
    ResumeSuggestion,
    ResumeVersion,
    ScanStatus,
)
from app.modules.resumes.scanner import MalwareScanner, ScannerUnavailableError
from app.modules.resumes.service import InvalidResumeError, parse_pdf
from app.modules.resumes.storage import ObjectStore, ObjectStoreError

RETRYABLE_ERRORS = {
    "resume_scan_unavailable",
    "resume_storage_unavailable",
    "resume_worker_interrupted",
}
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


async def claim_next_job(db: AsyncSession) -> UUID | None:
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
    job.safe_error_code = None
    await db.commit()
    return job.id


async def recover_stale_jobs(db: AsyncSession, *, stale_after_seconds: int = 300) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    jobs = list(
        (
            await db.scalars(
                select(ResumeProcessingJob)
                .options(selectinload(ResumeProcessingJob.resume_version))
                .where(
                    ResumeProcessingJob.status == JobStatus.PROCESSING.value,
                    ResumeProcessingJob.heartbeat_at < cutoff,
                    ResumeProcessingJob.attempts < ResumeProcessingJob.max_attempts,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for job in jobs:
        job.status = JobStatus.QUEUED.value
        job.safe_error_code = "resume_worker_interrupted"
        job.available_at = datetime.now(UTC)
        job.resume_version.status = ResumeStatus.QUEUED.value
        job.resume_version.safe_error_code = "resume_worker_interrupted"
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
) -> None:
    job = await db.scalar(
        select(ResumeProcessingJob)
        .options(
            selectinload(ResumeProcessingJob.resume_version).selectinload(
                ResumeVersion.suggestions
            )
        )
        .where(ResumeProcessingJob.id == job_id)
    )
    if job is None or job.status == JobStatus.COMPLETED.value:
        return
    version = job.resume_version
    if job.status != JobStatus.PROCESSING.value:
        job.status = JobStatus.PROCESSING.value
        job.attempts += 1
        job.started_at = datetime.now(UTC)
        await db.commit()
    version.status = ResumeStatus.PROCESSING.value
    await db.commit()

    try:
        data = store.read(version.storage_key)
        scan = await scanner.scan(data)
        version.scan_engine = scan.engine
        version.scanned_at = datetime.now(UTC)
        if not scan.clean:
            version.scan_status = ScanStatus.INFECTED.value
            raise InvalidResumeError("resume_malware_detected")
        version.scan_status = ScanStatus.CLEAN.value
        parsed = parse_pdf(data, settings.resume_max_pages)
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
        job.status = JobStatus.COMPLETED.value
        job.finished_at = datetime.now(UTC)
        job.safe_error_code = None
        await db.commit()
    except (InvalidResumeError, ObjectStoreError, ScannerUnavailableError) as error:
        code = str(error)
        retryable = code in RETRYABLE_ERRORS and job.attempts < job.max_attempts
        version.safe_error_code = code
        job.safe_error_code = code
        if isinstance(error, ScannerUnavailableError):
            version.scan_status = ScanStatus.FAILED.value
        if retryable:
            job.status = JobStatus.QUEUED.value
            job.available_at = datetime.now(UTC) + timedelta(seconds=min(2**job.attempts, 60))
            version.status = ResumeStatus.QUEUED.value
        else:
            job.status = JobStatus.FAILED.value
            job.finished_at = datetime.now(UTC)
            version.status = ResumeStatus.FAILED.value
        await db.commit()
