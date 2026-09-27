from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.auth import Institution, User, UserRole
from app.models.engagement import RoadmapProgress, RoadmapTemplate, StudentRoadmap
from app.models.onboarding import StudentProject
from app.models.profile import StudentProfile
from app.modules.auth.security import hash_password
from app.modules.engagement.schemas import NotificationCreate, RoadmapProgressUpdate
from app.modules.engagement.service import (
    EngagementError,
    current_roadmap,
    dashboard,
    list_notifications,
    list_templates,
    publish_notification,
    roadmap_availability,
    select_roadmap,
    update_roadmap_progress,
)
from app.modules.roadmaps.graph import LEGACY_ROADMAPS

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


async def seed_people(db):  # type: ignore[no-untyped-def]
    institution = Institution(code="ENGAGE-A", name="Engagement Institute")
    other = Institution(code="ENGAGE-B", name="Other Institute")
    db.add_all([institution, other])
    await db.flush()
    admin = User(
        institution_id=institution.id,
        email="admin-engage@example.edu",
        password_hash=hash_password("a sufficiently long password"),
        role=UserRole.TNP_ADMIN.value,
    )
    student = User(
        institution_id=institution.id,
        email="student-engage@example.edu",
        password_hash=hash_password("a sufficiently long password"),
        role=UserRole.STUDENT.value,
    )
    outsider = User(
        institution_id=other.id,
        email="outsider-engage@example.edu",
        password_hash=hash_password("a sufficiently long password"),
        role=UserRole.STUDENT.value,
    )
    db.add_all([admin, student, outsider])
    await db.commit()
    return institution, other, admin, student, outsider


async def test_eight_curated_paths_are_acyclic_and_progress_is_prerequisite_aware() -> None:
    async with Session() as db:
        institution, _, _, student, _ = await seed_people(db)
        db.add(
            StudentProfile(
                user_id=student.id,
                institution_id=institution.id,
                full_name="Asha Patil",
                target_roles=["Software Developer"],
            )
        )
        await db.flush()
        templates = await list_templates(db)
        assert len(templates) == 8
        assert templates[0].milestones
        assert templates[0].milestones[0].title
        availability = await roadmap_availability(db, institution.id, student.id)
        assert availability.status == "available"
        assert [item.title for item in availability.templates] == ["Software Developer"]
        selected = await select_roadmap(
            db, institution.id, student.id, availability.templates[0].id
        )
        assert selected.version == 2
        assert [node.state for node in selected.nodes].count("next") == 1
        locked = next(node for node in selected.nodes if node.state == "locked")
        with pytest.raises(EngagementError, match="prerequisites_incomplete"):
            await update_roadmap_progress(
                db,
                institution.id,
                student.id,
                locked.key,
                RoadmapProgressUpdate(completed=True, evidence_label="Too early"),
            )
        first = next(node for node in selected.nodes if node.state == "next")
        progressed = await update_roadmap_progress(
            db,
            institution.id,
            student.id,
            first.key,
            RoadmapProgressUpdate(
                completed=True,
                evidence_label="Reviewed project",
                evidence_reference="/resume",
            ),
        )
        assert progressed.completed_count == 1


async def test_backend_roadmap_has_role_specific_steps_and_recorded_evidence_context() -> None:
    async with Session() as db:
        institution, _, _, student, _ = await seed_people(db)
        profile = StudentProfile(
            user_id=student.id,
            institution_id=institution.id,
            full_name="Asha Patil",
            target_roles=["Backend Developer"],
            skills=[{"name": "FastAPI"}],
        )
        db.add(profile)
        await db.flush()
        db.add(
            StudentProject(
                profile_id=profile.id,
                title="Library API",
                description="A small REST service",
                technologies=["FastAPI"],
            )
        )
        await db.flush()

        availability = await roadmap_availability(db, institution.id, student.id)
        assert [item.slug for item in availability.templates] == ["backend-developer"]
        selected = await select_roadmap(
            db, institution.id, student.id, availability.templates[0].id
        )
        assert selected.nodes[0].title == "API foundations"
        assert selected.nodes[1].title == "Database design"
        assert selected.nodes[0].tasks[0].title
        assert "Library API" in selected.nodes[0].practice
        assert "recorded" in selected.nodes[0].why.lower()
        assert "verified" in selected.nodes[0].why.lower()


async def test_existing_completed_legacy_roadmap_keeps_its_original_milestone_meaning() -> None:
    async with Session() as db:
        institution, _, _, student, _ = await seed_people(db)
        db.add(
            StudentProfile(
                user_id=student.id,
                institution_id=institution.id,
                full_name="Asha Patil",
                target_roles=["Backend Developer"],
            )
        )
        await list_templates(db)
        title, summary, nodes = LEGACY_ROADMAPS["backend-developer"]
        legacy = RoadmapTemplate(
            slug="backend-developer",
            title=title,
            summary=summary,
            version=1,
            status="approved",
            approved_at=datetime.now(UTC),
            nodes=[
                {
                    "key": node.key,
                    "title": node.title,
                    "completion": node.completion,
                    "prerequisites": list(node.prerequisites),
                }
                for node in nodes
            ],
        )
        db.add(legacy)
        await db.flush()
        selected = StudentRoadmap(
            institution_id=institution.id,
            student_user_id=student.id,
            template_id=legacy.id,
        )
        db.add(selected)
        await db.flush()
        db.add(
            RoadmapProgress(
                student_roadmap_id=selected.id,
                node_key="fundamentals",
                status="completed",
                evidence={"label": "A small application"},
            )
        )
        await db.flush()

        current = await current_roadmap(db, institution.id, student.id)
        assert current is not None
        assert current.version == 1
        assert current.nodes[0].title == "Programming foundations"
        assert current.nodes[0].state == "completed"
        available = await roadmap_availability(db, institution.id, student.id)
        assert available.templates[0].version == 2
        with pytest.raises(EngagementError, match="progress_reset"):
            await select_roadmap(db, institution.id, student.id, available.templates[0].id)


async def test_roadmap_availability_explains_missing_targets_and_institution_policy() -> None:
    async with Session() as db:
        institution, _, _, student, _ = await seed_people(db)
        missing_target = await roadmap_availability(db, institution.id, student.id)
        assert missing_target.status == "no_target_role"
        assert missing_target.templates == []

        institution.roadmaps_enabled = False
        await db.flush()
        restricted = await roadmap_availability(db, institution.id, student.id)
        assert restricted.status == "institution_restriction"
        assert restricted.reason


async def test_roadmap_matches_common_role_name_and_offers_curated_fallback() -> None:
    async with Session() as db:
        institution, _, _, student, _ = await seed_people(db)
        profile = StudentProfile(
            user_id=student.id,
            institution_id=institution.id,
            full_name="Asha Patil",
            target_roles=["Software Engineer"],
        )
        db.add(profile)
        await db.flush()

        matched = await roadmap_availability(db, institution.id, student.id)
        assert matched.match_basis == "target_role"
        assert [item.title for item in matched.templates] == ["Software Developer"]

        profile.target_roles = ["Product Designer"]
        await db.flush()
        fallback = await roadmap_availability(db, institution.id, student.id)
        assert fallback.status == "available"
        assert fallback.match_basis == "self_selected"
        assert fallback.target_roles == ["Product Designer"]
        assert len(fallback.templates) == 8

        selected = await select_roadmap(db, institution.id, student.id, fallback.templates[0].id)
        assert selected.nodes


async def test_notifications_are_tenant_scoped_deduplicated_and_internal_link_safe() -> None:
    async with Session() as db:
        institution, _, admin, student, outsider = await seed_people(db)
        payload = NotificationCreate(
            recipient_user_id=student.id,
            event_key="application:1:shortlisted",
            title="Application shortlisted",
            body="Review the placement cell update and prepare the requested evidence.",
            deep_link="/opportunities/1",
        )
        first = await publish_notification(db, institution.id, admin.id, payload)
        second = await publish_notification(db, institution.id, admin.id, payload)
        assert first.id == second.id
        page = await list_notifications(db, institution.id, student.id)
        assert page.unread_count == 1
        assert len(page.items) == 1
        with pytest.raises(EngagementError, match="recipient_not_found"):
            await publish_notification(
                db,
                institution.id,
                admin.id,
                payload.model_copy(update={"recipient_user_id": outsider.id}),
            )
        with pytest.raises(ValueError, match="local paths"):
            NotificationCreate(
                recipient_user_id=student.id,
                event_key="unsafe:1",
                title="Unsafe link",
                body="This message must be rejected before persistence.",
                deep_link="//evil.example",
            )


async def test_dashboard_returns_exactly_one_explainable_next_action() -> None:
    async with Session() as db:
        institution, _, _, student, _ = await seed_people(db)
        db.add(
            StudentProfile(
                user_id=student.id,
                institution_id=institution.id,
                full_name="Asha Patil",
                department="Computer Science",
                education=[],
                target_roles=[],
                skills=[],
            )
        )
        await db.commit()
        response = await dashboard(db, institution.id, student.id)
        assert response.next_action.key == "complete_profile"
        assert response.next_action.policy_version == "placement-actions-v2"
        assert response.next_action.source_facts == ["required_profile_facts_incomplete"]
        assert response.next_action.estimated_minutes == 8
        assert response.next_action.unlocks == (
            "More complete role-specific eligibility explanations"
        )
        assert response.readiness.policy_version == "readiness-v2"
        assert response.readiness.completed_evidence == 0
        assert response.readiness.total_evidence == 3
        assert response.readiness.required_complete is False
        assert [stage.key for stage in response.activation] == [
            "account_activated",
            "profile_minimum",
            "target_role",
            "opportunities_unlocked",
            "first_application",
        ]
        assert response.activation[0].status == "complete"
        assert response.activation[1].status == "current"
        assert response.activation[-1].status == "upcoming"
        assert response.state == "incomplete"
