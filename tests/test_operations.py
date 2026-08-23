from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.auth import Institution, User, UserRole
from app.models.resume import (
    JobStatus,
    Resume,
    ResumeProcessingJob,
    ResumeStatus,
    ResumeVersion,
    ScanStatus,
)
from app.modules.auth.security import hash_password
from app.modules.operations.service import (
    OperationsError,
    cancel_resume_job,
    get_resume_job,
    list_resume_jobs,
    operations_summary,
)
from app.modules.resumes.pipeline import claim_next_job, recover_stale_jobs

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


async def seed_job(db, *, code: str = "OPS-A"):  # type: ignore[no-untyped-def]
    institution = Institution(code=code, name=f"Institution {code}")
    db.add(institution)
    await db.flush()
    user = User(
        institution_id=institution.id,
        email=f"student-{code.casefold()}@example.edu",
        password_hash=hash_password("a secure student passphrase"),
        role=UserRole.STUDENT.value,
    )
    db.add(user)
    await db.flush()
    resume = Resume(user_id=user.id, institution_id=institution.id)
    db.add(resume)
    await db.flush()
    version = ResumeVersion(
        resume_id=resume.id,
        user_id=user.id,
        institution_id=institution.id,
        version_number=1,
        storage_key=f"quarantine/{code}.pdf",
        original_name="resume.pdf",
        checksum=code.casefold().ljust(64, "0"),
        status=ResumeStatus.QUEUED.value,
        scan_status=ScanStatus.QUARANTINED.value,
        created_at=datetime.now(UTC),
    )
    db.add(version)
    await db.flush()
    job = ResumeProcessingJob(resume_version_id=version.id, max_attempts=2)
    db.add(job)
    await db.commit()
    return institution, job


async def test_claim_sets_a_bounded_lease_and_records_worker_identity() -> None:
    async with Session() as db:
        institution, job = await seed_job(db)
        claimed = await claim_next_job(db, worker_id="worker-test", lease_seconds=90)
        assert claimed == job.id
        refreshed = await get_resume_job(db, institution.id, job.id)
        assert refreshed.status == JobStatus.PROCESSING.value
        assert refreshed.claimed_by == "worker-test"
        assert refreshed.lease_expires_at is not None
        assert [(event.event_type, event.worker_id) for event in refreshed.events] == [
            ("claimed", "worker-test")
        ]


async def test_stale_exhausted_job_becomes_inspectable_terminal_failure() -> None:
    async with Session() as db:
        institution, job = await seed_job(db)
        job.status = JobStatus.PROCESSING.value
        job.attempts = job.max_attempts
        job.started_at = datetime.now(UTC) - timedelta(minutes=10)
        job.heartbeat_at = datetime.now(UTC) - timedelta(minutes=10)
        job.lease_expires_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.commit()

        assert await recover_stale_jobs(db, stale_after_seconds=60) == 1
        refreshed = await get_resume_job(db, institution.id, job.id)
        assert refreshed.status == JobStatus.FAILED.value
        assert refreshed.safe_error_code == "resume_worker_attempts_exhausted"
        assert refreshed.resume_version.status == ResumeStatus.FAILED.value
        assert refreshed.events[-1].event_type == "stale_lease_failed"


async def test_operator_actions_are_tenant_scoped_and_cancellation_is_terminal() -> None:
    async with Session() as db:
        institution, job = await seed_job(db)
        other, _ = await seed_job(db, code="OPS-B")
        with pytest.raises(OperationsError, match="resume_job_not_found"):
            await cancel_resume_job(
                db, other.id, job.id, correlation_id="cross-tenant-test"
            )

        cancelled = await cancel_resume_job(
            db, institution.id, job.id, correlation_id="operator-test"
        )
        assert cancelled.status == JobStatus.CANCELLED.value
        assert cancelled.events[-1].correlation_id == "operator-test"
        page = await list_resume_jobs(db, institution.id)
        assert page.total == 1
        summary = await operations_summary(db, institution.id)
        assert summary.status_counts == {JobStatus.CANCELLED.value: 1}
        assert summary.active_leases == 0
