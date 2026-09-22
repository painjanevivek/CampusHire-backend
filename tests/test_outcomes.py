from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_recruitment_operations import TestSession, database, publish_sample_role, seed_people

from app.models.recruitment import Application
from app.models.resume import ResumeVersion
from app.modules.experience.queries import operational_report
from app.modules.outcomes.schemas import OutcomeEventCreate
from app.modules.outcomes.service import (
    OutcomeError,
    create_outcome_event,
    list_outcome_events,
    outcome_totals,
)
from app.modules.recruitment.schemas import ApplicationCreate
from app.modules.recruitment.service import create_application

__all__ = ["database"]


async def _application(suffix: str = "outcomes"):
    db = TestSession()
    institution, officer, student = await seed_people(db, suffix)
    role, _ = await publish_sample_role(db, institution, officer, include_missing_rule=False)
    resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
    application, _ = await create_application(
        db,
        institution.id,
        student.id,
        f"{suffix}-application",
        ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
    )
    return db, institution, officer, student, application


async def test_offer_never_counts_as_joined_and_verified_joining_requires_evidence():
    db, institution, officer, _, application = await _application()
    try:
        await create_outcome_event(
            db,
            institution.id,
            officer.id,
            application.id,
            OutcomeEventCreate(
                event_type="offer_issued",
                outcome_state="verified",
                event_at=datetime.now(UTC),
                source_type="offer_letter",
                evidence_reference="private://synthetic-offer-letter",
            ),
        )
        totals = await outcome_totals(db, institution.id)
        assert totals.verified.get("offer_issued") == 1
        assert totals.verified.get("joining", 0) == 0

        with pytest.raises(OutcomeError, match="verified_evidence_required"):
            await create_outcome_event(
                db,
                institution.id,
                officer.id,
                application.id,
                OutcomeEventCreate(
                    event_type="joining",
                    outcome_state="verified",
                    event_at=datetime.now(UTC),
                    source_type="officer_confirmation",
                ),
            )
    finally:
        await db.close()


async def test_corrections_supersede_without_rewriting_history():
    db, institution, officer, student, application = await _application("outcome-correction")
    try:
        original = await create_outcome_event(
            db,
            institution.id,
            officer.id,
            application.id,
            OutcomeEventCreate(
                event_type="joining",
                outcome_state="provisional",
                event_at=datetime.now(UTC),
                source_type="student_report",
            ),
        )
        correction = await create_outcome_event(
            db,
            institution.id,
            officer.id,
            application.id,
            OutcomeEventCreate(
                event_type="joining_deferred",
                outcome_state="verified",
                event_at=datetime.now(UTC),
                source_type="employer_update",
                evidence_reference="private://synthetic-deferral",
                supersedes_event_id=original.id,
                correction_reason="Employer changed the joining date.",
            ),
        )
        events = await list_outcome_events(
            db, institution.id, application.id, student_user_id=student.id
        )
        assert [event.id for event in events] == [original.id, correction.id]
        assert events[0].superseded_by_event_id == correction.id
        assert events[0].event_type == "joining"
        totals = await outcome_totals(db, institution.id)
        assert totals.provisional.get("joining", 0) == 0
        assert totals.verified.get("joining_deferred") == 1
    finally:
        await db.close()


async def test_outcome_timeline_is_tenant_and_student_scoped():
    db, institution, officer, student, application = await _application("outcome-scope")
    try:
        await create_outcome_event(
            db,
            institution.id,
            officer.id,
            application.id,
            OutcomeEventCreate(
                event_type="selection",
                outcome_state="provisional",
                event_at=datetime.now(UTC),
                source_type="officer_record",
            ),
        )
        other, _, other_student = await seed_people(db, "outcome-other")
        with pytest.raises(OutcomeError, match="application_not_found"):
            await list_outcome_events(db, other.id, application.id)
        with pytest.raises(OutcomeError, match="application_not_found"):
            await list_outcome_events(
                db, institution.id, application.id, student_user_id=other_student.id
            )
        assert await db.get(Application, application.id) is not None
        assert len(
            await list_outcome_events(
                db, institution.id, application.id, student_user_id=student.id
            )
        ) == 1
    finally:
        await db.close()


async def test_frozen_report_is_repeatable_and_separates_outcome_states():
    db, institution, officer, _, application = await _application("outcome-report")
    try:
        event_at = datetime.now(UTC) - timedelta(minutes=1)
        await create_outcome_event(
            db,
            institution.id,
            officer.id,
            application.id,
            OutcomeEventCreate(
                event_type="joining",
                outcome_state="verified",
                event_at=event_at,
                source_type="employer_confirmation",
                evidence_reference="private://synthetic-joining",
            ),
        )
        start = event_at - timedelta(days=1)
        end = event_at + timedelta(days=1)
        first = await operational_report(db, institution.id, start, end)
        second = await operational_report(db, institution.id, start, end)
        first_outcomes = [item for item in first.metrics if item.key.startswith("outcome_")]
        second_outcomes = [item for item in second.metrics if item.key.startswith("outcome_")]
        assert first_outcomes == second_outcomes
        assert [(item.key, item.value) for item in first_outcomes] == [
            ("outcome_joining_verified", 1)
        ]
        assert first.definition.code == "placement_outcomes"
        assert first.definition.frozen_at == end
    finally:
        await db.close()


async def test_outcome_http_routes_enforce_role_tenant_and_read_only_platform_access():
    from httpx import ASGITransport, AsyncClient

    from app.core.database import get_db
    from app.main import app
    from app.models.auth import Session, User, UserRole
    from app.modules.auth.dependencies import (
        AuthenticatedPrincipal,
        get_current_principal,
        verify_authenticated_csrf,
    )
    from app.modules.auth.security import hash_password, hash_secret

    db, institution, officer, student, application = await _application("outcome-http")
    try:
        _, _, other_student = await seed_people(db, "outcome-http-other")
        reviewer = User(
            institution_id=institution.id,
            username="outcome-reviewer",
            email="outcome-reviewer@example.edu",
            password_hash=hash_password("a sufficiently long reviewer passphrase"),
            role=UserRole.TNP_REVIEWER.value,
        )
        platform_admin = User(
            institution_id=None,
            username="outcome-platform-admin",
            email="outcome-platform@example.test",
            password_hash=hash_password("a sufficiently long platform passphrase"),
            role=UserRole.PLATFORM_ADMIN.value,
        )
        db.add_all([reviewer, platform_admin])
        await db.commit()
    finally:
        await db.close()

    user = officer

    async def principal():
        return AuthenticatedPrincipal(
            user=user,
            membership=None,
            session=Session(
                user_id=user.id,
                token_hash=hash_secret("outcome-http-session"),
                csrf_hash=hash_secret("outcome-http-csrf"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                last_activity_at=datetime.now(UTC),
                mfa_verified_at=datetime.now(UTC),
            ),
        )

    async def database_override():
        async with TestSession() as scoped_db:
            yield scoped_db

    app.dependency_overrides[get_db] = database_override
    app.dependency_overrides[get_current_principal] = principal
    app.dependency_overrides[verify_authenticated_csrf] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            endpoint = f"/api/v1/tnp/recruitment/applications/{application.id}/outcomes"
            payload = {
                "event_type": "selection",
                "outcome_state": "provisional",
                "event_at": datetime.now(UTC).isoformat(),
                "source_type": "officer_record",
            }
            response = await client.post(endpoint, json=payload)
            assert response.status_code == 200
            user = reviewer
            assert (await client.post(endpoint, json=payload)).status_code == 403
            user = student
            assert (
                await client.get(f"/api/v1/applications/{application.id}/outcomes")
            ).status_code == 200
            user = other_student
            assert (
                await client.get(f"/api/v1/applications/{application.id}/outcomes")
            ).status_code == 404
            user = platform_admin
            assert (
                await client.get(
                    f"/api/v1/platform/institutions/{institution.id}"
                    f"/applications/{application.id}/outcomes"
                )
            ).status_code == 200
            assert (await client.post(endpoint, json=payload)).status_code == 403
    finally:
        app.dependency_overrides.clear()
