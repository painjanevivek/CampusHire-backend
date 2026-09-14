import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.ai.providers.base import StructuredGenerationResult
from app.ai.workflows.campus_agent import _validate_artifact
from app.core.config import Settings
from app.models import Base
from app.models.agentic import (
    AgentEvent,
    AgentRun,
    DrivePreparationArtifact,
    PreparationPlan,
    SourceVersion,
)
from app.models.auth import Institution, User, UserRole
from app.models.recruitment import Company, PlacementDrive, PlacementRole, PublicationStatus
from app.modules.agentic.evaluation import EvaluationAttempt, score_attempts
from app.modules.agentic.schemas import (
    ArtifactApply,
    ArtifactDecision,
    PracticeConsentUpdate,
    RunResume,
    TnpRunCreate,
)
from app.modules.agentic.service import (
    AgentRunNotFoundError,
    AgentRunValidationError,
    apply_drive_artifact,
    authorized_run,
    decide_artifact,
    delete_private_run,
    read_consent,
    resume_run,
    update_consent,
)
from app.modules.agentic.sources import SourceValidationError, _validate_external_url
from app.modules.agentic.worker import claim_next_agent_run, recover_stale_agent_runs
from app.modules.auth.security import hash_password


class SequenceGenerator:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)

    def generate_structured(
        self, *, prompt: str, response_schema: dict[str, Any]
    ) -> StructuredGenerationResult:
        assert prompt
        assert response_schema
        return StructuredGenerationResult(
            content=self.responses.pop(0),
            provider_name="test-provider",
            model_version="test-model",
            latency_ms=1,
            input_tokens=10,
            output_tokens=10,
        )


@asynccontextmanager
async def agent_database() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield session_factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def seed_recruitment_context(
    db: AsyncSession, *, code: str, email: str, role: str
) -> tuple[Institution, User, PlacementDrive, PlacementRole]:
    now = datetime.now(UTC)
    institution = Institution(code=code, name=f"{code} College")
    db.add(institution)
    await db.flush()
    user = User(
        institution_id=institution.id,
        email=email,
        password_hash=hash_password("a sufficiently long synthetic passphrase"),
        role=role,
    )
    company = Company(institution_id=institution.id, name=f"{code} Labs")
    db.add_all((user, company))
    await db.flush()
    drive = PlacementDrive(
        institution_id=institution.id,
        company_id=company.id,
        title="Graduate engineering",
        description="A reviewed graduate engineering drive.",
        location="Bengaluru",
        work_mode="hybrid",
        opens_at=now - timedelta(days=1),
        deadline_at=now + timedelta(days=30),
        status=PublicationStatus.PUBLISHED.value,
        published_at=now,
    )
    db.add(drive)
    await db.flush()
    placement_role = PlacementRole(
        institution_id=institution.id,
        drive_id=drive.id,
        title="Python Engineer",
        description="Build reliable Python services.",
        employment_type="full-time",
        location="Bengaluru",
        work_mode="hybrid",
        skills=["Python"],
        requirements=["B.Tech"],
        status=PublicationStatus.PUBLISHED.value,
        published_at=now,
    )
    db.add(placement_role)
    await db.commit()
    return institution, user, drive, placement_role


def agent_settings() -> Settings:
    return Settings(
        gemini_generation_model="test-model",
        ai_input_cost_cents_per_million_tokens=1,
        ai_output_cost_cents_per_million_tokens=1,
    )


def test_drive_run_requires_an_authorized_brief_or_source() -> None:
    with pytest.raises(ValidationError, match="recruiter brief"):
        TnpRunCreate(drive_id=uuid4(), expected_revision=1)


def test_agentic_benchmark_is_balanced_at_one_hundred_scenarios() -> None:
    fixture = Path(__file__).parent / "fixtures" / "agentic-evaluation-v1.json"
    dataset = json.loads(fixture.read_text(encoding="utf-8"))
    variants = dataset["variants_per_template"]
    assert len(dataset["templates"]) * variants == 100
    student_templates = sum(
        item["workflow"] == "prepare_opportunity" for item in dataset["templates"]
    )
    tnp_templates = sum(
        item["workflow"] == "prepare_drive" for item in dataset["templates"]
    )
    assert student_templates * variants == 50
    assert tnp_templates * variants == 50


def test_quality_gates_are_reported_separately_by_workflow() -> None:
    attempts = [
        EvaluationAttempt(
            scenario_id=f"{workflow}-1",
            workflow=workflow,
            repeat=repeat,
            task_completed=True,
            supported_claims=20,
            factual_claims=20,
            valid_citations=20,
            citations=20,
        )
        for workflow in ("prepare_opportunity", "prepare_drive")
        for repeat in range(1, 4)
    ]
    scores = score_attempts(attempts)
    assert [score.workflow for score in scores] == ["prepare_opportunity", "prepare_drive"]
    assert all(score.qualified for score in scores)


def test_private_network_source_is_rejected_even_if_domain_is_allowlisted() -> None:
    settings = Settings(source_allowed_domains=["localhost"])
    with pytest.raises(SourceValidationError, match="source_host_not_public"):
        _validate_external_url("https://localhost/course", settings)


def test_preparation_validation_preserves_deterministic_eligibility() -> None:
    run = SimpleNamespace(workflow="prepare_opportunity")
    evidence = [
        {
            "source_id": "role:1",
            "access_scope": "institution",
            "facts": "Python is a published role skill",
        }
    ]
    artifact = {
        "title": "Prepare for Python role",
        "summary": "A focused preparation plan for the published opportunity.",
        "eligibility": {
            "status": "eligible",
            "rule_version": "1",
            "reasons": [],
            "missing_evidence": [],
        },
        "priorities": [
            {
                "skill": "Python",
                "evidence_state": "unknown",
                "rationale": "Python is required for this role.",
                "source_ids": ["role:1"],
                "activities": [
                    {
                        "title": "Python exercise",
                        "objective": "Complete one role-focused Python exercise.",
                        "minutes": 60,
                        "due_offset_days": 2,
                        "resource_source_ids": [],
                    }
                ],
            }
        ],
        "unresolved_questions": [],
        "total_minutes": 60,
        "limitations": [],
    }
    context = {
        "eligibility": {
            "status": "ineligible",
            "rule_version": "1",
            "missing_evidence": [],
        }
    }
    errors = _validate_artifact(run, artifact, evidence, context)  # type: ignore[arg-type]
    assert "Eligibility status must match the deterministic result." in errors


@pytest.mark.asyncio
async def test_student_runs_are_private_while_drive_runs_are_shared_in_tenant() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with session_factory() as db:
            institution = Institution(code="agent-test", name="Agent Test College")
            owner = User(
                email="owner-agent@example.edu",
                password_hash=hash_password("a sufficiently long synthetic passphrase"),
                role=UserRole.STUDENT.value,
            )
            colleague = User(
                email="colleague-agent@example.edu",
                password_hash=hash_password("another sufficiently long synthetic passphrase"),
                role=UserRole.TNP_REVIEWER.value,
            )
            db.add_all((institution, owner, colleague))
            await db.flush()
            student_run = AgentRun(
                institution_id=institution.id,
                user_id=owner.id,
                audience="student",
                workflow="prepare_opportunity",
                target_kind="role",
                target_id=uuid4(),
                idempotency_key="student-run-1",
                input_payload={},
                checkpoint_data={},
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            drive_run = AgentRun(
                institution_id=institution.id,
                user_id=owner.id,
                audience="tnp",
                workflow="prepare_drive",
                target_kind="drive",
                target_id=uuid4(),
                idempotency_key="drive-run-1",
                input_payload={},
                checkpoint_data={},
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            db.add_all((student_run, drive_run))
            await db.commit()

            with pytest.raises(AgentRunNotFoundError):
                await authorized_run(
                    db,
                    run_id=student_run.id,
                    institution_id=institution.id,
                    user_id=colleague.id,
                    audience="student",
                )
            shared = await authorized_run(
                db,
                run_id=drive_run.id,
                institution_id=institution.id,
                user_id=colleague.id,
                audience="tnp",
            )
            assert shared.id == drive_run.id
            student_run.status = "cancelled"
            await db.flush()
            await delete_private_run(
                db,
                run_id=student_run.id,
                institution_id=institution.id,
                user_id=owner.id,
            )
            with pytest.raises(AgentRunNotFoundError):
                await authorized_run(
                    db,
                    run_id=student_run.id,
                    institution_id=institution.id,
                    user_id=owner.id,
                    audience="student",
                )
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.mark.asyncio
async def test_student_run_recovers_interrupts_resumes_and_accepts_with_evidence() -> None:
    from app.ai.workflows.campus_agent import process_agent_run

    async with agent_database() as session_factory:
        async with session_factory() as db:
            institution, student, _, role = await seed_recruitment_context(
                db,
                code="student-agent",
                email="student-agent@example.edu",
                role=UserRole.STUDENT.value,
            )
            run = AgentRun(
                institution_id=institution.id,
                user_id=student.id,
                audience="student",
                workflow="prepare_opportunity",
                target_kind="role",
                target_id=role.id,
                idempotency_key="student-agent-recovery",
                input_payload={
                    "role_id": str(role.id),
                    "goal": "Prepare for the published Python role",
                    "available_minutes_per_week": 300,
                    "target_date": (datetime.now(UTC) + timedelta(days=14)).date().isoformat(),
                    "existing_plan_id": None,
                },
                checkpoint_data={"stage": "created", "answers": []},
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            db.add(run)
            await db.commit()

            assert await claim_next_agent_run(db, worker_id="worker-a", lease_seconds=60) == run.id
            assert run.lease_owner == "worker-a"
            run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()

            assert await recover_stale_agent_runs(db) == 1
            await db.refresh(run)
            assert (run.status, run.revision, run.lease_owner) == ("queued", 3, None)
            recovered = await db.scalar(
                select(AgentEvent).where(
                    AgentEvent.run_id == run.id,
                    AgentEvent.event_type == "recovered",
                )
            )
            assert recovered is not None

            assert await claim_next_agent_run(db, worker_id="worker-b", lease_seconds=60) == run.id
            await process_agent_run(
                db,
                run.id,
                generator=SequenceGenerator(
                    {
                        "action": "request_clarification",
                        "reason": "A target outcome is needed before drafting.",
                        "clarification_question": (
                            "Which Python outcome should the plan prioritize?"
                        ),
                    }
                ),
                settings=agent_settings(),
            )
            await db.refresh(run)
            assert run.status == "awaiting_input"
            assert run.lease_owner is None
            assert run.lease_expires_at is None
            interrupt_id = str(run.required_action["interrupt_id"])
            with pytest.raises(
                AgentRunValidationError,
                match="cancel_active_run_before_deleting",
            ):
                await delete_private_run(
                    db,
                    run_id=run.id,
                    institution_id=institution.id,
                    user_id=student.id,
                )

            await resume_run(
                db,
                run_id=run.id,
                institution_id=institution.id,
                user_id=student.id,
                audience="student",
                payload=RunResume(
                    expected_revision=run.revision,
                    interrupt_id=interrupt_id,
                    response="Prioritize a small Python API exercise.",
                ),
            )
            assert await claim_next_agent_run(db, worker_id="worker-c", lease_seconds=60) == run.id
            await process_agent_run(
                db,
                run.id,
                generator=SequenceGenerator(
                    {
                        "action": "draft_artifact",
                        "reason": "The reviewed evidence now supports a bounded plan.",
                        "clarification_question": None,
                    },
                    {
                        "title": "Prepare for the Python Engineer role",
                        "summary": "A bounded plan based on the published Python requirement.",
                        "eligibility": {
                            "status": "unavailable",
                            "rule_version": None,
                            "reasons": [],
                            "missing_evidence": [],
                        },
                        "priorities": [
                            {
                                "skill": "Python",
                                "evidence_state": "unknown",
                                "rationale": "Python is a published role skill.",
                                "source_ids": [f"role:{role.id}"],
                                "activities": [
                                    {
                                        "title": "Python API exercise",
                                        "objective": (
                                            "Complete one role-focused Python API exercise."
                                        ),
                                        "minutes": 60,
                                        "due_offset_days": 2,
                                        "resource_source_ids": [],
                                    }
                                ],
                            }
                        ],
                        "unresolved_questions": [],
                        "total_minutes": 60,
                        "limitations": [
                            "No proficiency was inferred from missing resume evidence."
                        ],
                    },
                ),
                settings=agent_settings(),
            )
            await db.refresh(run)
            assert run.status == "awaiting_review"
            assert run.lease_owner is None
            plan = await db.scalar(select(PreparationPlan).where(PreparationPlan.run_id == run.id))
            assert plan is not None
            assert any(
                reference["source_id"] == f"role:{role.id}"
                for reference in plan.evidence_references
            )

            accepted = await decide_artifact(
                db,
                artifact_id=plan.id,
                institution_id=institution.id,
                user_id=student.id,
                audience="student",
                payload=ArtifactDecision(expected_revision=plan.revision, decision="accept"),
            )
            await db.refresh(run)
            assert accepted.status == "accepted"
            assert run.status == "completed"
            with pytest.raises(AgentRunValidationError, match="artifact_already_decided"):
                await decide_artifact(
                    db,
                    artifact_id=plan.id,
                    institution_id=institution.id,
                    user_id=student.id,
                    audience="student",
                    payload=ArtifactDecision(
                        expected_revision=accepted.revision,
                        decision="reject",
                    ),
                )


@pytest.mark.asyncio
async def test_tnp_run_uses_fresh_approved_source_and_applies_only_selected_field() -> None:
    from app.ai.workflows.campus_agent import process_agent_run

    async with agent_database() as session_factory:
        async with session_factory() as db:
            institution, reviewer, drive, _ = await seed_recruitment_context(
                db,
                code="tnp-agent",
                email="tnp-agent@example.edu",
                role=UserRole.TNP_REVIEWER.value,
            )
            drive.status = PublicationStatus.DRAFT.value
            drive.published_at = None
            source = SourceVersion(
                institution_id=institution.id,
                source_type="official_career_page",
                canonical_url="https://careers.example.edu/graduate-python",
                title="Reviewed recruiter role page",
                version=1,
                review_status="approved",
                access_scope="institution",
                permitted_use="drive preparation",
                source_metadata={"published_title": "Graduate Python Drive"},
                content_digest="a" * 64,
                retrieved_at=datetime.now(UTC),
                last_verified_at=datetime.now(UTC),
                active=True,
            )
            db.add(source)
            await db.flush()
            original_description = drive.description
            run = AgentRun(
                institution_id=institution.id,
                user_id=reviewer.id,
                audience="tnp",
                workflow="prepare_drive",
                target_kind="drive",
                target_id=drive.id,
                idempotency_key="tnp-agent-source",
                input_payload={
                    "drive_id": str(drive.id),
                    "expected_revision": drive.revision,
                    "recruiter_brief": "Use the reviewed Graduate Python Drive title only.",
                    "source_version_ids": [str(source.id)],
                },
                checkpoint_data={"stage": "created", "answers": []},
                expires_at=datetime.now(UTC) + timedelta(days=30),
            )
            db.add(run)
            await db.commit()

            assert (
                await claim_next_agent_run(db, worker_id="tnp-worker", lease_seconds=60)
                == run.id
            )
            await process_agent_run(
                db,
                run.id,
                generator=SequenceGenerator(
                    {
                        "action": "draft_artifact",
                        "reason": "The approved source supports a review draft.",
                        "clarification_question": None,
                    },
                    {
                        "field_proposals": [
                            {
                                "field": "title",
                                "proposed_value": "Graduate Python Drive",
                                "rationale": (
                                    "The approved source uses the Graduate Python Drive title."
                                ),
                                "source_ids": [f"source:{source.id}"],
                            }
                        ],
                        "clarification_questions": [],
                        "announcement_draft": "Review draft for the Graduate Python Drive.",
                        "blockers": [],
                        "unresolved_work": [],
                    },
                ),
                settings=agent_settings(),
            )
            artifact = await db.scalar(
                select(DrivePreparationArtifact).where(DrivePreparationArtifact.run_id == run.id)
            )
            assert artifact is not None
            assert any(
                reference["source_id"] == f"source:{source.id}"
                and reference["version"] == "1"
                for reference in artifact.evidence_references
            )
            accepted = await decide_artifact(
                db,
                artifact_id=artifact.id,
                institution_id=institution.id,
                user_id=reviewer.id,
                audience="tnp",
                payload=ArtifactDecision(expected_revision=artifact.revision, decision="accept"),
            )

            with pytest.raises(ValidationError):
                ArtifactApply(
                    expected_revision=accepted.revision,
                    expected_drive_revision=drive.revision,
                    fields=[],
                )
            with pytest.raises(AgentRunValidationError, match="selected_field_not_proposed"):
                await apply_drive_artifact(
                    db,
                    artifact_id=artifact.id,
                    institution_id=institution.id,
                    payload=ArtifactApply(
                        expected_revision=accepted.revision,
                        expected_drive_revision=drive.revision,
                        fields=["description"],
                    ),
                )

            applied = await apply_drive_artifact(
                db,
                artifact_id=artifact.id,
                institution_id=institution.id,
                payload=ArtifactApply(
                    expected_revision=accepted.revision,
                    expected_drive_revision=drive.revision,
                    fields=["title"],
                ),
            )
            await db.refresh(drive)
            assert applied.status == "applied"
            assert drive.title == "Graduate Python Drive"
            assert drive.description == original_description


@pytest.mark.asyncio
async def test_practice_consent_is_student_scoped_and_revocable() -> None:
    async with agent_database() as session_factory:
        async with session_factory() as db:
            institution = Institution(code="consent-agent", name="Consent Agent College")
            db.add(institution)
            await db.flush()
            first = User(
                institution_id=institution.id,
                email="first-consent@example.edu",
                password_hash=hash_password("a sufficiently long synthetic passphrase"),
                role=UserRole.STUDENT.value,
            )
            second = User(
                institution_id=institution.id,
                email="second-consent@example.edu",
                password_hash=hash_password("another sufficiently long synthetic passphrase"),
                role=UserRole.STUDENT.value,
            )
            db.add_all((first, second))
            await db.commit()

            assert not (await read_consent(
                db, institution_id=institution.id, student_id=first.id
            )).opted_in
            granted = await update_consent(
                db,
                institution_id=institution.id,
                student_id=first.id,
                payload=PracticeConsentUpdate(consent_version="1", opted_in=True),
            )
            assert granted.opted_in
            assert granted.granted_at is not None
            assert not (await read_consent(
                db, institution_id=institution.id, student_id=second.id
            )).opted_in

            revoked = await update_consent(
                db,
                institution_id=institution.id,
                student_id=first.id,
                payload=PracticeConsentUpdate(consent_version="1", opted_in=False),
            )
            assert not revoked.opted_in
            assert revoked.granted_at == granted.granted_at
            assert revoked.revoked_at is not None
