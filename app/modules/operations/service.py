from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.resume import JobStatus, ResumeProcessingJob, ResumeStatus, ResumeVersion
from app.modules.operations.schemas import (
    OperationsSummaryResponse,
    ResumeJobEventResponse,
    ResumeJobOperatorResponse,
    ResumeJobPage,
)
from app.modules.resumes.pipeline import RETRYABLE_ERRORS, record_job_event


class OperationsError(RuntimeError):
    pass


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _response(job: ResumeProcessingJob) -> ResumeJobOperatorResponse:
    return ResumeJobOperatorResponse(
        id=job.id,
        resume_version_id=job.resume_version_id,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        available_at=job.available_at,
        started_at=job.started_at,
        heartbeat_at=job.heartbeat_at,
        lease_expires_at=job.lease_expires_at,
        claimed_by=job.claimed_by,
        cancellation_requested_at=job.cancellation_requested_at,
        finished_at=job.finished_at,
        duration_ms=job.duration_ms,
        safe_error_code=job.safe_error_code,
        events=[
            ResumeJobEventResponse.model_validate(event, from_attributes=True)
            for event in sorted(job.events, key=lambda value: value.occurred_at)
        ],
    )


def _scoped_job_query(institution_id: UUID) -> Select[tuple[ResumeProcessingJob]]:
    return (
        select(ResumeProcessingJob)
        .join(ResumeVersion, ResumeVersion.id == ResumeProcessingJob.resume_version_id)
        .options(
            selectinload(ResumeProcessingJob.events),
            selectinload(ResumeProcessingJob.resume_version),
        )
        .where(ResumeVersion.institution_id == institution_id)
    )


async def list_resume_jobs(
    db: AsyncSession,
    institution_id: UUID,
    *,
    status_filter: str | None = None,
    limit: int = 50,
) -> ResumeJobPage:
    query = _scoped_job_query(institution_id)
    count_query = (
        select(func.count())
        .select_from(ResumeProcessingJob)
        .join(ResumeVersion, ResumeVersion.id == ResumeProcessingJob.resume_version_id)
        .where(ResumeVersion.institution_id == institution_id)
    )
    if status_filter is not None:
        allowed = {item.value for item in JobStatus}
        if status_filter not in allowed:
            raise OperationsError("resume_job_status_invalid")
        query = query.where(ResumeProcessingJob.status == status_filter)
        count_query = count_query.where(ResumeProcessingJob.status == status_filter)
    jobs = list(
        (
            await db.scalars(
                query.order_by(ResumeProcessingJob.created_at.desc()).limit(limit)
            )
        ).all()
    )
    total = int((await db.scalar(count_query)) or 0)
    return ResumeJobPage(items=[_response(job) for job in jobs], total=total)


async def get_resume_job(
    db: AsyncSession, institution_id: UUID, job_id: UUID, *, lock: bool = False
) -> ResumeProcessingJob:
    query = _scoped_job_query(institution_id).where(ResumeProcessingJob.id == job_id)
    if lock:
        query = query.with_for_update()
    job = await db.scalar(query.execution_options(populate_existing=True))
    if job is None:
        raise OperationsError("resume_job_not_found")
    return job


async def cancel_resume_job(
    db: AsyncSession,
    institution_id: UUID,
    job_id: UUID,
    *,
    correlation_id: str | None,
) -> ResumeJobOperatorResponse:
    job = await get_resume_job(db, institution_id, job_id, lock=True)
    if job.status in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value}:
        raise OperationsError("resume_job_not_cancellable")
    now = datetime.now(UTC)
    job.cancellation_requested_at = now
    if job.status == JobStatus.PROCESSING.value:
        job.status = JobStatus.CANCELLATION_REQUESTED.value
        record_job_event(db, job, "cancellation_requested", correlation_id=correlation_id)
    else:
        job.status = JobStatus.CANCELLED.value
        job.resume_version.status = ResumeStatus.CANCELLED.value
        job.safe_error_code = "resume_job_cancelled"
        job.resume_version.safe_error_code = "resume_job_cancelled"
        job.finished_at = now
        job.claimed_by = None
        job.lease_expires_at = None
        record_job_event(db, job, "cancelled_by_operator", correlation_id=correlation_id)
    await db.commit()
    return _response(await get_resume_job(db, institution_id, job_id))


async def retry_resume_job(
    db: AsyncSession,
    institution_id: UUID,
    job_id: UUID,
    *,
    correlation_id: str | None,
) -> ResumeJobOperatorResponse:
    job = await get_resume_job(db, institution_id, job_id, lock=True)
    if (
        job.status != JobStatus.FAILED.value
        or job.safe_error_code not in RETRYABLE_ERRORS
        or job.attempts >= job.max_attempts
    ):
        raise OperationsError("resume_job_not_retryable")
    job.status = JobStatus.QUEUED.value
    job.available_at = datetime.now(UTC)
    job.finished_at = None
    job.duration_ms = None
    job.cancellation_requested_at = None
    job.resume_version.status = ResumeStatus.QUEUED.value
    job.resume_version.safe_error_code = None
    record_job_event(db, job, "operator_retry_queued", correlation_id=correlation_id)
    await db.commit()
    return _response(await get_resume_job(db, institution_id, job_id))


async def operations_summary(
    db: AsyncSession, institution_id: UUID
) -> OperationsSummaryResponse:
    rows = (
        await db.execute(
            select(ResumeProcessingJob.status, func.count())
            .join(ResumeVersion, ResumeVersion.id == ResumeProcessingJob.resume_version_id)
            .where(ResumeVersion.institution_id == institution_id)
            .group_by(ResumeProcessingJob.status)
        )
    ).all()
    counts = {status: int(count) for status, count in rows}
    oldest_queued = await db.scalar(
        select(func.min(ResumeProcessingJob.available_at))
        .join(ResumeVersion, ResumeVersion.id == ResumeProcessingJob.resume_version_id)
        .where(
            ResumeVersion.institution_id == institution_id,
            ResumeProcessingJob.status == JobStatus.QUEUED.value,
        )
    )
    now = datetime.now(UTC)
    oldest_age = (
        max(0, int((now - _utc(oldest_queued)).total_seconds()))
        if oldest_queued is not None
        else None
    )
    active_leases = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(ResumeProcessingJob)
                .join(ResumeVersion, ResumeVersion.id == ResumeProcessingJob.resume_version_id)
                .where(
                    ResumeVersion.institution_id == institution_id,
                    ResumeProcessingJob.status.in_(
                        (
                            JobStatus.PROCESSING.value,
                            JobStatus.CANCELLATION_REQUESTED.value,
                        )
                    ),
                    ResumeProcessingJob.lease_expires_at > now,
                )
            )
        )
        or 0
    )
    exhausted = int(
        (
            await db.scalar(
                select(func.count())
                .select_from(ResumeProcessingJob)
                .join(ResumeVersion, ResumeVersion.id == ResumeProcessingJob.resume_version_id)
                .where(
                    ResumeVersion.institution_id == institution_id,
                    ResumeProcessingJob.status == JobStatus.FAILED.value,
                    ResumeProcessingJob.attempts >= ResumeProcessingJob.max_attempts,
                )
            )
        )
        or 0
    )
    return OperationsSummaryResponse(
        status_counts=counts,
        oldest_queued_age_seconds=oldest_age,
        active_leases=active_leases,
        exhausted_failures=exhausted,
    )


def resume_job_response(job: ResumeProcessingJob) -> ResumeJobOperatorResponse:
    return _response(job)
