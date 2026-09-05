from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_recruitment_operations import TestSession, database, publish_sample_role, seed_people

from app.models.recruitment import ApplicationDraft, PlacementDrive
from app.models.resume import ResumeVersion
from app.modules.engagement.service import dashboard, list_notifications, mark_notification_read
from app.modules.experience.priorities import action_sort_key, placement_actions
from app.modules.experience.publishing import publication_preview
from app.modules.experience.queries import operational_report, preparation, review_queue
from app.modules.experience.schemas import (
    RequestCreate,
    RequestResolution,
    RequestResponseCreate,
    SavedViewCreate,
)
from app.modules.experience.service import (
    ExperienceError,
    create_request,
    request_page,
    resolve_request,
    respond_to_request,
)
from app.modules.recruitment.schemas import ApplicationCreate, ApplicationStatusUpdate
from app.modules.recruitment.service import create_application, update_application_status

# Reuse the recruitment fixture so this exercises real, immutable application records.
__all__ = ["database"]


async def test_duplicate_drive_flushes_roles_before_dependent_rules():
    from unittest.mock import patch

    from app.models.recruitment import EligibilityRuleSet, PlacementRole
    from app.modules.recruitment.service import duplicate_drive

    async with TestSession() as db:
        institution, admin, _ = await seed_people(db, "duplicate-order")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        original_flush = db.flush

        async def check_foreign_key_order(*args, **kwargs):
            pending_roles = {item.id for item in db.new if isinstance(item, PlacementRole)}
            assert not any(
                isinstance(item, EligibilityRuleSet) and item.role_id in pending_roles
                for item in db.new
            ), "Flush roles before adding dependent rule rows"
            return await original_flush(*args, **kwargs)

        with patch.object(db, "flush", side_effect=check_foreign_key_order):
            clone = await duplicate_drive(db, institution.id, role.drive_id, admin.id)
        assert clone.status == "draft"


async def test_preparation_uses_only_explicit_approved_institution_mappings():
    from app.models.engagement import RoadmapTemplate
    from app.models.experience import ReviewedPreparationMapping

    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        other, other_admin, _ = await seed_people(db, "mapping-other")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        role.skills = ["Python"]
        template = RoadmapTemplate(
            slug="mapping-test",
            title="Reviewed Python",
            version=1,
            summary="Synthetic approved test template",
            status="approved",
            approved_at=datetime.now(UTC),
            nodes=[
                {"key": "api", "title": "Test an API", "completion": "Record passing API tests"}
            ],
        )
        db.add(template)
        await db.flush()
        mapping = ReviewedPreparationMapping(
            institution_id=institution.id,
            template_id=template.id,
            node_key="api",
            requirement="Python",
            reviewed_by=admin.id,
            reviewed_at=datetime.now(UTC),
        )
        db.add(mapping)
        db.add(
            ReviewedPreparationMapping(
                institution_id=other.id,
                template_id=template.id,
                node_key="api",
                requirement="Python",
                reviewed_by=other_admin.id,
                reviewed_at=datetime.now(UTC),
            )
        )
        await db.flush()
        result = await preparation(db, institution.id, student.id, role.id)
        assert len(result.activities) == 1
        assert result.activities[0]["title"] == "Test an API"
        mapping.status = "revoked"
        await db.flush()
        assert not (await preparation(db, institution.id, student.id, role.id)).activities
        mapping.status = "approved"
        institution.roadmaps_enabled = False
        await db.flush()
        assert not (await preparation(db, institution.id, student.id, role.id)).activities


async def test_http_experience_roles_and_saved_view_ownership():
    from httpx import ASGITransport, AsyncClient

    from app.core.database import get_db
    from app.main import app
    from app.models.auth import Session
    from app.modules.auth.dependencies import (
        AuthenticatedPrincipal,
        get_current_principal,
        verify_authenticated_csrf,
    )
    from app.modules.auth.security import hash_secret

    async with TestSession() as db:
        institution, admin, student = await seed_people(db, "http-experience")
        _, _, other = await seed_people(db, "http-other")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "http-request",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        await db.commit()

    user = student

    async def principal():
        return AuthenticatedPrincipal(
            user=user,
            membership=None,
            session=Session(
                user_id=user.id,
                token_hash=hash_secret("synthetic-session"),
                csrf_hash=hash_secret("synthetic-csrf"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                last_activity_at=datetime.now(UTC),
                mfa_verified_at=datetime.now(UTC),
            ),
        )

    async def database_override():
        async with TestSession() as db:
            yield db

    app.dependency_overrides[get_db] = database_override
    app.dependency_overrides[get_current_principal] = principal
    app.dependency_overrides[verify_authenticated_csrf] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/opportunity-views",
                json={"name": "Closing soon", "filters": {"sort": "deadline"}},
            )
            assert response.status_code == 200
            view_id = response.json()["id"]
            for path in ["review-queue", "reports", f"review-queue/{application.id}"]:
                assert (await client.get("/api/v1/admin/recruitment/" + path)).status_code == 403
            user = other
            assert (await client.get("/api/v1/opportunity-views")).json() == []
            assert (await client.delete(f"/api/v1/opportunity-views/{view_id}")).status_code == 404
            assert (
                await client.put(
                    f"/api/v1/opportunity-views/{view_id}",
                    json={"name": "Wrong owner", "filters": {}},
                )
            ).status_code == 404
            assert (
                await client.get(f"/api/v1/applications/{application.id}/requests")
            ).status_code == 404
            user = student
            assert (
                await client.put(
                    f"/api/v1/opportunity-views/{view_id}", json={"name": "Renamed", "filters": {}}
                )
            ).status_code == 200
            assert (await client.delete(f"/api/v1/opportunity-views/{view_id}")).status_code == 204
            user = admin
            assert (await client.get("/api/v1/opportunity-views")).status_code == 403
            assert (await client.get("/api/v1/admin/recruitment/review-queue")).json()["total"] == 1
    finally:
        app.dependency_overrides.clear()


async def test_correction_lifecycle_preserves_submission_and_rejects_stale_writes():
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "experience-test",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        snapshot = dict(application.resume_snapshot)
        request = await create_request(
            db,
            institution.id,
            admin.id,
            application.id,
            RequestCreate(
                instructions="Please explain your project contribution.",
                deadline_at=datetime.now(UTC) - timedelta(hours=1),
            ),
        )
        with pytest.raises(ExperienceError, match="not_found"):
            await request_page(db, institution.id, application.id, admin.id)
        response = await respond_to_request(
            db,
            institution.id,
            student.id,
            application.id,
            request.id,
            RequestResponseCreate(
                expected_revision=1,
                body="I implemented and tested the backend API.",
                resume_version_id=resume.id,
            ),
        )
        assert response.status == "awaiting_review"
        with pytest.raises(ExperienceError, match="revision_conflict"):
            await resolve_request(
                db,
                institution.id,
                admin.id,
                application.id,
                request.id,
                RequestResolution(expected_revision=1, action="resolve", body="Evidence reviewed."),
            )
        resolved = await resolve_request(
            db,
            institution.id,
            admin.id,
            application.id,
            request.id,
            RequestResolution(expected_revision=2, action="resolve", body="Evidence reviewed."),
        )
        assert resolved.status == "resolved"
        assert len(resolved.events) == 3
        assert application.resume_snapshot == snapshot
        assert application.status == "submitted"


async def test_application_revision_and_terminal_request_cancellation():
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "experience-revision",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        await update_application_status(
            db,
            institution.id,
            application.id,
            admin.id,
            ApplicationStatusUpdate(status="under_review", expected_revision=1),
        )
        with pytest.raises(ValueError, match="revision_conflict"):
            await update_application_status(
                db,
                institution.id,
                application.id,
                admin.id,
                ApplicationStatusUpdate(status="shortlisted", expected_revision=1),
            )
        await create_request(
            db,
            institution.id,
            admin.id,
            application.id,
            RequestCreate(instructions="Please clarify your academic evidence."),
        )
        await update_application_status(
            db,
            institution.id,
            application.id,
            admin.id,
            ApplicationStatusUpdate(
                status="rejected",
                expected_revision=application.revision,
                reason="The reviewed evidence does not meet this role's rules.",
            ),
        )
        page = await request_page(db, institution.id, application.id, student.id)
        assert page[0].status == "cancelled"
        assert page[0].events[-1].body


async def test_priorities_notifications_and_request_reopening():
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "priority-test",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        first = await create_request(
            db,
            institution.id,
            admin.id,
            application.id,
            RequestCreate(
                instructions="Clarify the ownership of your project.",
                deadline_at=datetime.now(UTC) - timedelta(days=1),
            ),
        )
        await create_request(
            db,
            institution.id,
            admin.id,
            application.id,
            RequestCreate(instructions="Provide the remaining academic information."),
        )
        result = await dashboard(db, institution.id, student.id)
        assert result.next_action.key == f"correction:{first.id}"
        assert len(result.upcoming) <= 5
        notifications = await list_notifications(db, institution.id, student.id)
        notice = next(n for n in notifications.items if n.related_request_id == first.id)
        await mark_notification_read(db, institution.id, student.id, notice.id)
        assert (
            await dashboard(db, institution.id, student.id)
        ).next_action.key == result.next_action.key
        response = await respond_to_request(
            db,
            institution.id,
            student.id,
            application.id,
            first.id,
            RequestResponseCreate(
                expected_revision=1, body="I designed and tested the API endpoints."
            ),
        )
        reopened = await resolve_request(
            db,
            institution.id,
            admin.id,
            application.id,
            first.id,
            RequestResolution(
                expected_revision=response.revision,
                action="reopen",
                body="Please include the test evidence as well.",
            ),
        )
        assert reopened.status == "open" and reopened.revision == 3
        assert reopened.events[1].actor_user_id == student.id
        await respond_to_request(
            db,
            institution.id,
            student.id,
            application.id,
            first.id,
            RequestResponseCreate(
                expected_revision=3, body="The test report covers the API validation."
            ),
        )
        notices = await list_notifications(db, institution.id, student.id)
        assert all(
            n.category == "updates" for n in notices.items if n.related_request_id == first.id
        )


async def test_tenant_isolation_reports_and_preparation_sources():
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        other_institution, _, other_student = await seed_people(db, "other")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "isolation-test",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        request = await create_request(
            db,
            institution.id,
            admin.id,
            application.id,
            RequestCreate(instructions="Please clarify the evidence listed here."),
        )
        with pytest.raises(ExperienceError, match="application_not_found"):
            await request_page(db, other_institution.id, application.id)
        with pytest.raises(ExperienceError, match="application_not_found"):
            await respond_to_request(
                db,
                institution.id,
                other_student.id,
                application.id,
                request.id,
                RequestResponseCreate(
                    expected_revision=1, body="An unauthorized student response."
                ),
            )
        assert (await review_queue(db, other_institution.id)).total == 0
        report = await operational_report(db, institution.id)
        count = next(metric for metric in report.metrics if metric.key == "awaiting_review")
        assert (
            count.value
            == (
                await review_queue(
                    db,
                    institution.id,
                    review_pending=True,
                    start_at=report.start_at,
                    end_at=report.end_at,
                )
            ).total
            == 1
        )
        assert next(m for m in report.metrics if m.key == "turnaround").value is None
        assert next(m for m in report.metrics if m.key == "requests_open").value == 1
        with pytest.raises(ExperienceError, match="report_date_range_invalid"):
            await operational_report(
                db, institution.id, datetime.now(UTC), datetime.now(UTC) - timedelta(days=1)
            )
        evidence = await preparation(db, institution.id, student.id, role.id, resume.id)
        assert evidence.source_resume_version_id == resume.id
        assert evidence.source_profile_revision is not None
        assert "No approved" in evidence.mapping_status
        with pytest.raises(ValueError, match="not_found"):
            await preparation(db, other_institution.id, other_student.id, role.id)
        foreign_resume = await db.scalar(
            select(ResumeVersion).where(ResumeVersion.user_id == other_student.id)
        )
        with pytest.raises(ExperienceError, match="reviewed_resume_not_found"):
            await preparation(db, institution.id, student.id, role.id, foreign_resume.id)


async def test_draft_priorities_exclude_expired_and_submitted_and_explain_prerequisites():
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        drive = await db.get(PlacementDrive, role.drive_id)
        now = datetime.now(UTC)
        drive.deadline_at = now + timedelta(hours=24)
        draft = ApplicationDraft(
            institution_id=institution.id,
            student_user_id=student.id,
            role_id=role.id,
            expires_at=now + timedelta(hours=25),
            last_saved_at=now,
        )
        db.add(draft)
        await db.flush()
        fallback = (await dashboard(db, institution.id, student.id)).next_action
        primary, upcoming = await placement_actions(
            db, institution.id, student.id, fallback, False, False, True, now
        )
        assert primary.key == f"draft:{draft.id}" and primary.href == "/onboarding"
        assert "first" in primary.description
        draft.expires_at = now - timedelta(seconds=1)
        await db.flush()
        fresh_fallback = fallback.model_copy(update={"key": "add_resume", "href": "/resume"})
        primary, upcoming = await placement_actions(
            db, institution.id, student.id, fresh_fallback, True, False, True, now
        )
        assert primary.key == "resume_processing"
        assert not any(item.key.startswith("draft:") for item in upcoming)


def test_action_ties_are_stable_and_saved_filters_are_bounded():
    now = datetime.now(UTC)
    assert action_sort_key(0, now, now, "a") < action_sort_key(0, now, now, "b")
    assert action_sort_key(0, now, now, "z") < action_sort_key(1, now, now, "a")
    assert (
        SavedViewCreate(name="Python roles", filters={"q": "Python", "sort": "newest"}).filters[
            "sort"
        ]
        == "newest"
    )
    for filters in (
        {"student_id": str(uuid4())},
        {"sort": "untrusted"},
        {"deadline_within_days": "999"},
    ):
        with pytest.raises(ValueError):
            SavedViewCreate(name="Invalid filter", filters=filters)


async def test_publication_preview_is_read_only_and_reports_blockers():
    async with TestSession() as db:
        institution, admin, _ = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        drive = await db.get(PlacementDrive, role.drive_id)
        before = drive.status
        preview = await publication_preview(db, institution.id, drive.id)
        assert not preview.blockers
        assert preview.roles[0].rules and drive.status == before
        drive.deadline_at = datetime.now(UTC) - timedelta(days=1)
        await db.flush()
        assert (
            "The application deadline has elapsed."
            in (await publication_preview(db, institution.id, drive.id)).blockers
        )
        with pytest.raises(ExperienceError, match="drive_not_found"):
            await publication_preview(db, uuid4(), drive.id)
