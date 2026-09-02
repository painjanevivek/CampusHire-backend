from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.auth import Session, User, UserRole
from app.models.communications import ProductEvent
from app.models.resume import (
    ResumeProcessingJob,
    ResumeStatus,
    ResumeVersion,
    ScanStatus,
    SuggestionStatus,
)
from app.modules.auth.security import hash_password, hash_secret
from app.modules.profiles.schemas import IdentityUpdate
from app.modules.profiles.service import ProfileConflictError, get_or_create, update_profile
from app.modules.resumes.builder import ResumeContent
from app.modules.resumes.parser import ParsedResume
from app.modules.resumes.pipeline import claim_next_job, process_job, recover_stale_jobs
from app.modules.resumes.scanner import MarkerScanner, ScannerUnavailableError, ScanResult
from app.modules.resumes.schemas import (
    ExtractionFieldDecision,
    ExtractionReviewRequest,
    SuggestionBatchItem,
    SuggestionDecisionRequest,
    SuggestionReviewBatch,
)
from app.modules.resumes.storage import LocalObjectStore
from app.modules.resumes.workflow import (
    ResumeWorkflowError,
    create_generated_version,
    create_uploaded_version,
    decide_suggestion,
    delete_owned_version,
    get_owned_version,
    review_extraction,
    review_suggestions_batch,
)

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    async def override_db() -> AsyncIterator[AsyncSession]:
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def create_user(db: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password("a sufficiently long test passphrase"),
        role=UserRole.STUDENT.value,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def create_session(db: AsyncSession, user: User, token: str, csrf: str) -> None:
    now = datetime.now(UTC)
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_secret(token),
            csrf_hash=hash_secret(csrf),
            expires_at=now + timedelta(hours=1),
            last_activity_at=now,
        )
    )
    await db.commit()


def sample_resume_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Asha Patil\nasha@example.edu\nB.Tech Computer Science\nPython SQL FastAPI\n"
        "Worked on a placement workflow",
    )
    data = document.tobytes()
    document.close()
    return data


def resume_content() -> ResumeContent:
    return ResumeContent(
        full_name="Asha Patil",
        email="asha@example.edu",
        summary="Computer science student building reliable software with reviewed evidence.",
        skills=["Python", "SQL", "FastAPI", "React"],
        projects=["Built a deterministic placement workflow"],
        education=["B.Tech Computer Science"],
    )


class UnavailableScanner:
    async def scan(self, _: bytes) -> ScanResult:
        raise ScannerUnavailableError("resume_scan_unavailable")


class DeterministicParser:
    def parse(self, data: bytes, *, max_bytes: int, max_pages: int) -> ParsedResume:
        assert len(data) <= max_bytes
        document = pymupdf.open(stream=data, filetype="pdf")
        try:
            assert document.page_count <= max_pages
            return ParsedResume(
                page_count=document.page_count,
                text="\n".join(document[index].get_text() for index in range(document.page_count)),
            )
        finally:
            document.close()


@pytest.mark.asyncio
async def test_profile_revisions_prevent_lost_updates() -> None:
    async with TestSession() as db:
        user = await create_user(db, "profile@example.edu")
        profile = await get_or_create(db, user)
        assert profile.revision == 1

        updated = await update_profile(
            db,
            user,
            IdentityUpdate(expected_revision=1, full_name="Asha Patil"),
        )
        assert updated.revision == 2

        with pytest.raises(ProfileConflictError) as conflict:
            await update_profile(
                db,
                user,
                IdentityUpdate(expected_revision=1, full_name="Stale Name"),
            )
        assert conflict.value.current_revision == 2
        assert (await get_or_create(db, user)).full_name == "Asha Patil"


@pytest.mark.asyncio
async def test_resume_pipeline_requires_review_and_rejects_unsupported_claims(
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite://",
        resume_storage_path=str(tmp_path / "resumes"),
        resume_parser_backend="subprocess",
    )
    store = LocalObjectStore(settings.resume_storage_path)
    async with TestSession() as db:
        user = await create_user(db, "resume@example.edu")
        uploaded = await create_uploaded_version(
            db,
            user_id=user.id,
            institution_id=None,
            data=sample_resume_pdf(),
            filename="../../Asha<resume>.pdf",
            content_type="application/pdf",
            store=store,
            settings=settings,
        )
        assert uploaded.status == ResumeStatus.QUEUED.value
        assert uploaded.scan_status == ScanStatus.QUARANTINED.value

        job_id = await claim_next_job(db)
        assert job_id == uploaded.job_id
        assert job_id is not None
        claimed = await db.get(ResumeProcessingJob, job_id)
        assert claimed is not None
        claimed.heartbeat_at = datetime(2020, 1, 1, tzinfo=UTC)
        await db.commit()
        assert await recover_stale_jobs(db, stale_after_seconds=1) == 1
        assert await claim_next_job(db) == job_id
        await process_job(
            db,
            job_id,
            store=store,
            scanner=MarkerScanner(),
            parser=DeterministicParser(),
            settings=settings,
        )

        version = await get_owned_version(db, user.id, uploaded.id)
        assert version.status == ResumeStatus.REVIEW_REQUIRED.value
        assert version.scan_status == ScanStatus.CLEAN.value
        assert version.original_name == "Asha_resume_.pdf"
        assert version.extracted_data["proposed"]["email"] == "asha@example.edu"
        assert version.suggestions[0].status == SuggestionStatus.PENDING.value

        decisions = [
            ExtractionFieldDecision(field_path=field, action="accept")
            for field in version.extracted_data["proposed"]
        ]
        version = await review_extraction(
            db,
            user_id=user.id,
            version_id=version.id,
            payload=ExtractionReviewRequest(expected_revision=0, decisions=decisions),
        )
        suggestion = version.suggestions[0]
        with pytest.raises(ResumeWorkflowError, match="resume_suggestion_unsupported_claim"):
            await decide_suggestion(
                db,
                user_id=user.id,
                version_id=version.id,
                suggestion_id=suggestion.id,
                payload=SuggestionDecisionRequest(
                    expected_revision=1,
                    action="edit",
                    edited_text="Increased conversion by 40%",
                ),
            )

        completed = await review_suggestions_batch(
            db,
            user_id=user.id,
            version_id=version.id,
            payload=SuggestionReviewBatch(
                expected_revision=1,
                decisions=[
                    SuggestionBatchItem(
                        suggestion_id=suggestion.id,
                        action="accept",
                    )
                ]
            ),
        )
        assert completed.status == ResumeStatus.COMPLETED.value
        assert completed.review_completed_at is not None
        completion_event = await db.scalar(
            select(ProductEvent).where(ProductEvent.event_name == "resume_completed")
        )
        assert completion_event is not None
        with pytest.raises(ResumeWorkflowError, match="resume_not_ready_for_review"):
            await review_extraction(
                db,
                user_id=user.id,
                version_id=version.id,
                payload=ExtractionReviewRequest(expected_revision=2, decisions=decisions),
            )


@pytest.mark.asyncio
async def test_resume_review_revision_rejects_stale_tab_updates(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite://",
        resume_storage_path=str(tmp_path / "resumes"),
        resume_parser_backend="subprocess",
    )
    store = LocalObjectStore(settings.resume_storage_path)
    async with TestSession() as db:
        user = await create_user(db, "review-conflict@example.edu")
        uploaded = await create_uploaded_version(
            db,
            user_id=user.id,
            institution_id=None,
            data=sample_resume_pdf(),
            filename="resume.pdf",
            content_type="application/pdf",
            store=store,
            settings=settings,
        )
        assert uploaded.job_id is not None
        await process_job(
            db,
            uploaded.job_id,
            store=store,
            scanner=MarkerScanner(),
            parser=DeterministicParser(),
            settings=settings,
        )
        version = await get_owned_version(db, user.id, uploaded.id)
        fields = list(version.extracted_data["proposed"])
        await review_extraction(
            db,
            user_id=user.id,
            version_id=version.id,
            payload=ExtractionReviewRequest(
                expected_revision=0,
                decisions=[ExtractionFieldDecision(field_path=fields[0], action="accept")],
            ),
        )
        with pytest.raises(ResumeWorkflowError, match="resume_review_revision_conflict"):
            await review_extraction(
                db,
                user_id=user.id,
                version_id=version.id,
                payload=ExtractionReviewRequest(
                    expected_revision=0,
                    decisions=[ExtractionFieldDecision(field_path=fields[-1], action="reject")],
                ),
            )


@pytest.mark.asyncio
async def test_generated_versions_are_immutable_and_ownership_scoped(tmp_path: Path) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite://",
        resume_storage_path=str(tmp_path / "resumes"),
        resume_parser_backend="subprocess",
    )
    store = LocalObjectStore(settings.resume_storage_path)
    async with TestSession() as db:
        owner = await create_user(db, "owner@example.edu")
        other = await create_user(db, "other@example.edu")
        generated = await create_generated_version(
            db,
            user_id=owner.id,
            institution_id=None,
            content=resume_content(),
            store=store,
            settings=settings,
        )
        assert generated.version_number == 1
        assert generated.status == ResumeStatus.COMPLETED.value
        assert store.read(generated.storage_key).startswith(b"%PDF-")

        with pytest.raises(ResumeWorkflowError, match="resume_not_found"):
            await get_owned_version(db, other.id, generated.id)

        await delete_owned_version(
            db,
            user_id=owner.id,
            version_id=generated.id,
            store=store,
        )
        assert await db.get(ResumeVersion, generated.id) is None
        assert not (Path(settings.resume_storage_path) / generated.storage_key).exists()


@pytest.mark.asyncio
async def test_scanner_outage_retries_without_losing_the_authoritative_job(
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite://",
        resume_storage_path=str(tmp_path / "retry-resumes"),
        resume_parser_backend="subprocess",
    )
    store = LocalObjectStore(settings.resume_storage_path)
    async with TestSession() as db:
        user = await create_user(db, "retry@example.edu")
        uploaded = await create_uploaded_version(
            db,
            user_id=user.id,
            institution_id=None,
            data=sample_resume_pdf(),
            filename="resume.pdf",
            content_type="application/pdf",
            store=store,
            settings=settings,
        )
        job_id = await claim_next_job(db)
        assert job_id is not None
        await process_job(
            db,
            job_id,
            store=store,
            scanner=UnavailableScanner(),
            settings=settings,
        )
        retrying = await get_owned_version(db, user.id, uploaded.id)
        assert retrying.status == ResumeStatus.QUEUED.value
        assert retrying.processing_job is not None
        assert retrying.processing_job.safe_error_code == "resume_scan_unavailable"

        await process_job(
            db,
            job_id,
            store=store,
            scanner=MarkerScanner(),
            parser=DeterministicParser(),
            settings=settings,
        )
        recovered = await get_owned_version(db, user.id, uploaded.id)
        assert recovered.status == ResumeStatus.REVIEW_REQUIRED.value
        assert recovered.scan_status == ScanStatus.CLEAN.value


@pytest.mark.asyncio
async def test_resume_download_route_fails_closed_for_another_student(
    tmp_path: Path, client: TestClient
) -> None:
    settings = get_settings()
    original_storage_path = settings.resume_storage_path
    settings.resume_storage_path = str(tmp_path / "api-resumes")
    try:
        async with TestSession() as db:
            owner = await create_user(db, "route-owner@example.edu")
            other = await create_user(db, "route-other@example.edu")
            await create_session(db, owner, "owner-session", "owner-csrf")
            await create_session(db, other, "other-session", "other-csrf")

        client.cookies.set(settings.session_cookie_name, "owner-session")
        client.cookies.set(settings.csrf_cookie_name, "owner-csrf")
        uploaded = client.post(
            "/api/v1/resumes",
            headers={"Origin": "http://localhost:3000", "X-CSRF-Token": "owner-csrf"},
            files={"file": ("resume.pdf", sample_resume_pdf(), "application/pdf")},
        )
        assert uploaded.status_code == 202, uploaded.text
        resume_id = uploaded.json()["id"]

        async with TestSession() as db:
            job_id = await claim_next_job(db)
            assert job_id is not None
            await process_job(
                db,
                job_id,
                store=LocalObjectStore(settings.resume_storage_path),
                scanner=MarkerScanner(),
                parser=DeterministicParser(),
                settings=settings,
            )

        owner_download = client.get(f"/api/v1/resumes/{resume_id}/download")
        assert owner_download.status_code == 200
        assert owner_download.content.startswith(b"%PDF-")
        assert owner_download.headers["cache-control"] == "private, no-store"

        client.cookies.set(settings.session_cookie_name, "other-session")
        client.cookies.set(settings.csrf_cookie_name, "other-csrf")
        denied = client.get(f"/api/v1/resumes/{resume_id}/download")
        assert denied.status_code == 404
    finally:
        settings.resume_storage_path = original_storage_path
