from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.auth import Institution, InstitutionMembership, MembershipStatus, User, UserRole
from app.models.privacy import DataDeletionRequest
from app.models.profile import StudentProfile
from app.models.recruitment import Application
from app.models.resume import Resume, ResumeProcessingJob, ResumeVersion, ScanStatus
from app.modules.auth.security import hash_password
from app.modules.privacy.service import (
    PrivacyError,
    process_next_deletion_cleanup,
    request_student_deletion,
)
from app.modules.resumes.storage import LocalObjectStore, ObjectStoreError

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


async def seed_student(db):  # type: ignore[no-untyped-def]
    institution = Institution(code="PRIVACY-A", name="Privacy Institute")
    db.add(institution)
    await db.flush()
    student = User(
        institution_id=institution.id,
        email="privacy-student@example.edu",
        password_hash=hash_password("a secure student passphrase"),
        role=UserRole.STUDENT.value,
    )
    db.add(student)
    await db.flush()
    db.add(
        StudentProfile(
            user_id=student.id,
            institution_id=institution.id,
            full_name="Privacy Student",
        )
    )
    await db.commit()
    return institution, student


async def test_deletion_removes_authoritative_data_then_retries_private_cleanup(
    tmp_path: Path,
) -> None:
    store = LocalObjectStore(str(tmp_path / "private-resumes"))
    key = store.put_quarantined(b"%PDF-1.4 private")
    async with Session() as db:
        institution, student = await seed_student(db)
        resume = Resume(user_id=student.id, institution_id=institution.id)
        db.add(resume)
        await db.flush()
        version = ResumeVersion(
            resume_id=resume.id,
            user_id=student.id,
            institution_id=institution.id,
            version_number=1,
            storage_key=key,
            original_name="resume.pdf",
            checksum="a" * 64,
            scan_status=ScanStatus.QUARANTINED.value,
            created_at=datetime.now(UTC),
        )
        db.add(version)
        await db.flush()
        db.add(ResumeProcessingJob(resume_version_id=version.id))
        await db.commit()

        response = await request_student_deletion(
            db,
            user_id=student.id,
            institution_id=institution.id,
            correlation_id="privacy-request-123",
            account_wide=True,
        )
        assert response.status == "pending"
        assert await db.get(User, student.id) is None
        assert await db.scalar(
            select(StudentProfile).where(StudentProfile.user_id == student.id)
        ) is None
        assert await db.scalar(
            select(ResumeVersion).where(ResumeVersion.user_id == student.id)
        ) is None
        assert store.read(key).startswith(b"%PDF")

        assert await process_next_deletion_cleanup(db, store=store) == response.id
        request = await db.get(DataDeletionRequest, response.id)
        assert request is not None
        assert request.status == "completed"
        assert request.object_keys == []
        with pytest.raises(ObjectStoreError, match="resume_storage_unavailable"):
            store.read(key)


async def test_application_snapshot_creates_an_explicit_retention_hold() -> None:
    async with Session() as db:
        institution, student = await seed_student(db)
        db.add(
            Application(
                institution_id=institution.id,
                role_id=uuid4(),
                student_user_id=student.id,
                resume_version_id=uuid4(),
                eligibility_evaluation_id=uuid4(),
                idempotency_key="privacy-hold-test",
                role_snapshot={},
                resume_snapshot={},
                facts_snapshot={},
                rule_snapshot={},
                eligibility_snapshot={},
            )
        )
        await db.commit()

        with pytest.raises(PrivacyError, match="student_data_retention_hold"):
            await request_student_deletion(
                db,
                user_id=student.id,
                institution_id=institution.id,
                correlation_id="privacy-hold-123",
                account_wide=True,
            )
        assert await db.get(User, student.id) is not None


async def test_account_wide_deletion_requires_explicit_scope_and_covers_all_memberships() -> None:
    async with Session() as db:
        first, student = await seed_student(db)
        second = Institution(code="PRIVACY-B", name="Second Privacy Institute")
        db.add(second)
        await db.flush()
        db.add_all(
            [
                InstitutionMembership(
                    institution_id=first.id,
                    user_id=student.id,
                    role=UserRole.STUDENT.value,
                    status=MembershipStatus.ACTIVE.value,
                ),
                InstitutionMembership(
                    institution_id=second.id,
                    user_id=student.id,
                    role=UserRole.STUDENT.value,
                    status=MembershipStatus.ACTIVE.value,
                ),
            ]
        )
        await db.commit()

        with pytest.raises(PrivacyError, match="account_wide_confirmation_required"):
            await request_student_deletion(
                db,
                user_id=student.id,
                institution_id=first.id,
                correlation_id="privacy-scope-missing",
                account_wide=False,
            )
        assert await db.get(User, student.id) is not None

        await request_student_deletion(
            db,
            user_id=student.id,
            institution_id=first.id,
            correlation_id="privacy-account-wide",
            account_wide=True,
        )
        assert await db.get(User, student.id) is None


async def test_private_cleanup_recovers_an_expired_processing_lease(tmp_path: Path) -> None:
    store = LocalObjectStore(str(tmp_path / "private-resumes"))
    key = store.put_quarantined(b"%PDF-1.4 retry")
    async with Session() as db:
        request = DataDeletionRequest(
            user_id=uuid4(),
            status="processing",
            object_keys=[key],
            attempts=1,
            max_attempts=3,
            available_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        db.add(request)
        await db.commit()

        assert await process_next_deletion_cleanup(db, store=store, lease_seconds=60) == request.id
        await db.refresh(request)
        assert request.status == "completed"
        assert request.attempts == 1


async def test_private_cleanup_records_a_safe_terminal_failure() -> None:
    class UnavailableStore:
        def delete(self, _: str) -> None:
            raise ObjectStoreError("provider secret must not escape")

    async with Session() as db:
        request = DataDeletionRequest(
            user_id=uuid4(),
            status="pending",
            object_keys=["opaque.pdf"],
            attempts=0,
            max_attempts=1,
        )
        db.add(request)
        await db.commit()

        assert await process_next_deletion_cleanup(db, store=UnavailableStore()) == request.id  # type: ignore[arg-type]
        await db.refresh(request)
        assert request.status == "failed"
        assert request.safe_error_code == "private_object_cleanup_unavailable"
        assert "secret" not in request.safe_error_code
