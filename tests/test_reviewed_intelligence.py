from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.auth import Institution, User, UserRole
from app.models.profile import StudentProfile
from app.models.recruitment import PlacementRole, PublicationStatus
from app.models.resume import ResumeStatus, ResumeVersion, ScanStatus
from app.modules.auth.security import hash_password
from app.modules.intelligence.schemas import (
    ExtractionCreate,
    ExtractionReview,
    PolicyCreate,
    PolicyQuestion,
    PolicyReview,
    PolicySectionInput,
)
from app.modules.intelligence.service import (
    IntelligenceError,
    answer_policy_question,
    create_extraction,
    create_policy,
    list_policies,
    review_extraction,
    review_policy,
    semantic_match,
)
from app.modules.intelligence.vector_store import tenant_query_filter, tenant_vector_payload

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


class FixedEmbedder:
    def embed(self, text: str) -> list[float]:
        return [1.0, 0.25 if "Python" in text else 0.1, 0.5]


async def seed_context(db: AsyncSession):  # type: ignore[no-untyped-def]
    institution = Institution(code="INST-A", name="Institution A")
    other = Institution(code="INST-B", name="Institution B")
    db.add_all([institution, other])
    await db.flush()
    admin = User(
        institution_id=institution.id,
        email="admin@example.edu",
        password_hash=hash_password("a sufficiently long password"),
        role=UserRole.TNP_ADMIN.value,
    )
    student = User(
        institution_id=institution.id,
        email="student@example.edu",
        password_hash=hash_password("a sufficiently long password"),
        role=UserRole.STUDENT.value,
    )
    db.add_all([admin, student])
    await db.flush()
    profile = StudentProfile(
        user_id=student.id,
        institution_id=institution.id,
        full_name="Sensitive Name",
        prn="PRIVATE-123",
        phone="+91 9999999999",
        department="Computer Science",
        skills=[{"name": "Python", "proficiency": "strong"}],
        target_roles=["Software Engineer"],
        revision=3,
    )
    resume = ResumeVersion(
        user_id=student.id,
        institution_id=institution.id,
        version_number=2,
        storage_key="clean/student/resume.pdf",
        original_name="resume.pdf",
        checksum="reviewed-intelligence-checksum",
        status=ResumeStatus.COMPLETED.value,
        scan_status=ScanStatus.CLEAN.value,
        extracted_data={"summary": "Python developer", "projects": ["API platform"]},
    )
    role = PlacementRole(
        institution_id=institution.id,
        drive_id=uuid4(),
        title="Software Engineer",
        description="Build reliable Python services.",
        employment_type="full-time",
        location="Bengaluru",
        work_mode="hybrid",
        skills=["Python", "SQL"],
        requirements=["Reviewed project evidence"],
        status=PublicationStatus.PUBLISHED.value,
        published_at=datetime.now(UTC),
    )
    # SQLite foreign keys are disabled in this focused service fixture; the role id is all we need.
    db.add_all([profile, resume, role])
    await db.commit()
    return institution, other, admin, student, role


async def test_match_is_versioned_separate_and_degrades_without_provider() -> None:
    async with Session() as db:
        institution, _, _, student, role = await seed_context(db)
        available = await semantic_match(
            db,
            institution_id=institution.id,
            student_user_id=student.id,
            role_id=role.id,
            embedder=FixedEmbedder(),
        )
        assert available.status == "available"
        assert available.score is not None
        assert available.scoring_version == "match-v1"
        assert set(available.components) == {
            "semantic_similarity",
            "skill_coverage",
            "project_evidence",
        }

        role.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        unavailable = await semantic_match(
            db,
            institution_id=institution.id,
            student_user_id=student.id,
            role_id=role.id,
            embedder=None,
        )
        assert unavailable.status == "unavailable"
        assert unavailable.safe_error_code == "semantic_provider_unavailable"


async def test_only_approved_policy_is_grounded_and_reviewed_extraction_changes_draft_role() -> (
    None
):
    async with Session() as db:
        institution, other, admin, _, role = await seed_context(db)
        policy = await create_policy(
            db,
            institution.id,
            admin.id,
            PolicyCreate(
                title="Placement policy",
                source_reference="Registrar circular 2026-08",
                sections=[
                    PolicySectionInput(
                        section="Eligibility 4.2",
                        page=7,
                        text="Students with missing attendance evidence require manual review.",
                    )
                ],
            ),
        )
        before = await answer_policy_question(
            db, institution.id, PolicyQuestion(question="What happens when attendance is missing?")
        )
        assert before.grounded is False
        reviewed = await review_policy(
            db,
            institution.id,
            admin.id,
            policy.id,
            PolicyReview(action="approve", reason="Verified against the registrar circular."),
        )
        assert reviewed.status == "approved"
        after = await answer_policy_question(
            db, institution.id, PolicyQuestion(question="What happens when attendance is missing?")
        )
        assert after.grounded is True
        assert after.policy_version == 1
        unrelated = await answer_policy_question(
            db,
            institution.id,
            PolicyQuestion(question="Does the policy mention orbital mechanics?"),
        )
        assert unrelated.grounded is False
        assert await list_policies(db, other.id) == []

        role.status = PublicationStatus.DRAFT.value
        proposal = await create_extraction(
            db,
            institution.id,
            admin.id,
            role.id,
            ExtractionCreate(
                source_text=(
                    "Requirements:\n- Strong Python fundamentals\n"
                    "- Experience with Docker deployment"
                )
            ),
        )
        assert proposal.status == "draft"
        accepted = await review_extraction(
            db,
            institution.id,
            admin.id,
            proposal.id,
            ExtractionReview(
                action="approve",
                reason="Compared line by line with the signed role brief.",
                requirements=["Strong Python fundamentals", "Experience with Docker deployment"],
                skills=["Python", "Docker"],
            ),
        )
        assert accepted.status == "approved"
        assert role.skills == ["Python", "Docker"]
        with pytest.raises(IntelligenceError, match="review_already_final"):
            await review_extraction(
                db,
                institution.id,
                admin.id,
                proposal.id,
                ExtractionReview(
                    action="reject", reason="This second decision must not be accepted."
                ),
            )


def test_vector_metadata_and_queries_are_tenant_scoped() -> None:
    payload = tenant_vector_payload(
        institution_id="inst-1",
        owner_id="student-1",
        source_id="resume-2",
        model="gemini-embedding-001",
        version="v1",
    )
    assert payload["institution_id"] == "inst-1"
    assert tenant_query_filter("inst-1") == {
        "must": [{"key": "institution_id", "match": {"value": "inst-1"}}]
    }
