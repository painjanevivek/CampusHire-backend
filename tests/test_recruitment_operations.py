from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.auth import Institution, Session, User, UserRole
from app.models.profile import StudentProfile
from app.models.resume import ResumeStatus, ResumeVersion, ScanStatus
from app.modules.auth.dependencies import (
    AuthenticatedPrincipal,
    get_current_principal,
    get_tenant_context,
    verify_authenticated_csrf,
)
from app.modules.auth.security import hash_password, hash_secret
from app.modules.recruitment.schemas import (
    ApplicationAppealCreate,
    ApplicationAppealResolution,
    ApplicationCreate,
    ApplicationOverrideCreate,
    ApplicationStatusUpdate,
    ApplicationWithdrawal,
    CompanyCreate,
    DriveCreate,
    RoleCreate,
    RuleSetCreate,
)
from app.modules.recruitment.service import (
    RecruitmentError,
    application_deadline_calendar,
    create_application,
    create_application_appeal,
    create_company,
    create_drive,
    create_role,
    create_rule_set,
    get_student_application,
    list_admin_applications,
    list_opportunities,
    override_application,
    publish_role,
    publish_rule_set,
    resolve_application_appeal,
    response_for_application,
    transition_drive,
    update_application_status,
    withdraw_application,
)
from app.modules.resumes.builder import ResumeContent, generate_pdf

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


async def seed_people(db: AsyncSession, suffix: str = "one") -> tuple[Institution, User, User]:
    institution = Institution(code=f"CAMPUS-{suffix}", name=f"Campus {suffix}")
    db.add(institution)
    await db.flush()
    admin = User(
        institution_id=institution.id,
        email=f"admin-{suffix}@example.edu",
        password_hash=hash_password("a sufficiently long admin passphrase"),
        role=UserRole.TNP_ADMIN.value,
    )
    student = User(
        institution_id=institution.id,
        email=f"student-{suffix}@example.edu",
        password_hash=hash_password("a sufficiently long student passphrase"),
        role=UserRole.STUDENT.value,
    )
    db.add_all([admin, student])
    await db.flush()
    db.add(
        StudentProfile(
            user_id=student.id,
            institution_id=institution.id,
            full_name="Asha Patil",
            department="Computer Science",
            education=[
                {
                    "degree": "B.Tech",
                    "branch": "Computer Science",
                    "institution": institution.name,
                    "start_year": 2023,
                    "graduation_year": 2027,
                    "score": 8.4,
                    "score_scale": "cgpa_10",
                }
            ],
            skills=[{"name": "Python", "proficiency": "strong"}],
            target_roles=["Software Developer"],
            external_links={"github": "https://github.com/asha"},
            is_complete=True,
        )
    )
    pdf = generate_pdf(
        ResumeContent(
            full_name="Asha Patil",
            email=student.email,
            summary="Computer science student building reliable placement software.",
            skills=["Python", "SQL"],
            projects=["Placement workflow"],
            education=["B.Tech Computer Science"],
        )
    )
    resume = ResumeVersion(
        user_id=student.id,
        institution_id=institution.id,
        version_number=1,
        source="generated",
        storage_key=f"clean/{student.id}/resume.pdf",
        original_name="resume-v1.pdf",
        checksum=f"checksum-{suffix}",
        content_type="application/pdf",
        size_bytes=len(pdf),
        status=ResumeStatus.COMPLETED.value,
        scan_status=ScanStatus.CLEAN.value,
        extracted_data={},
    )
    db.add(resume)
    await db.commit()
    await db.refresh(institution)
    await db.refresh(admin)
    await db.refresh(student)
    return institution, admin, student


async def publish_sample_role(
    db: AsyncSession,
    institution: Institution,
    admin: User,
    *,
    include_missing_rule: bool,
):
    company = await create_company(
        db,
        institution.id,
        CompanyCreate(name="Nexora Labs", website_url="https://example.com"),
    )
    drive = await create_drive(
        db,
        institution.id,
        DriveCreate(
            company_id=company.id,
            title="Engineering Drive 2027",
            description="A reviewed campus placement drive for software roles.",
            location="Bengaluru, India",
            work_mode="hybrid",
            opens_at=datetime.now(UTC) - timedelta(days=1),
            deadline_at=datetime.now(UTC) + timedelta(days=7),
        ),
    )
    role = await create_role(
        db,
        institution.id,
        drive.id,
        RoleCreate(
            title="Software Engineer",
            description="Build reliable product systems with a cross-functional engineering team.",
            employment_type="full-time",
            location="Bengaluru, India",
            work_mode="hybrid",
            salary_display="INR 8–10 LPA",
            skills=["Python", "SQL"],
            requirements=["B.Tech", "CGPA 7.0 or above"],
        ),
    )
    rules = [
        {"field": "degree", "operator": "eq", "value": "B.Tech", "label": "Degree"},
        {"field": "cgpa", "operator": "gte", "value": 7.0, "label": "Minimum CGPA"},
    ]
    if include_missing_rule:
        rules.append(
            {
                "field": "active_backlogs",
                "operator": "lte",
                "value": 0,
                "label": "Active backlogs",
            }
        )
    rule_set = await create_rule_set(
        db, institution.id, role.id, admin.id, RuleSetCreate(rules=rules)
    )
    await publish_rule_set(db, institution.id, role.id, rule_set.id)
    await publish_role(db, institution.id, role.id)
    await transition_drive(db, institution.id, drive.id, "publish")
    await db.commit()
    return role, rule_set


@pytest.mark.asyncio
async def test_missing_facts_require_review_and_same_snapshot_is_deterministic() -> None:
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=True)
        first = await list_opportunities(
            db,
            institution.id,
            student.id,
            query=None,
            location=None,
            work_mode=None,
            skill=None,
            saved_only=False,
            page=1,
            page_size=20,
        )
        second = await list_opportunities(
            db,
            institution.id,
            student.id,
            query=None,
            location=None,
            work_mode=None,
            skill=None,
            saved_only=False,
            page=1,
            page_size=20,
        )
        assert first.items[0].id == role.id
        assert first.items[0].eligibility.status == "needs_manual_review"
        assert first.items[0].eligibility == second.items[0].eligibility
        assert first.items[0].eligibility.missing_evidence == ["Active backlogs"]


@pytest.mark.asyncio
async def test_application_is_idempotent_and_preserves_immutable_decision_inputs() -> None:
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, rule_set = await publish_sample_role(
            db, institution, admin, include_missing_rule=False
        )
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        assert resume is not None
        payload = ApplicationCreate(role_id=role.id, resume_version_id=resume.id)
        application, replayed = await create_application(
            db, institution.id, student.id, "application-key-001", payload
        )
        await db.commit()
        replay, was_replayed = await create_application(
            db, institution.id, student.id, "application-key-001", payload
        )
        assert not replayed
        assert was_replayed
        assert replay.id == application.id
        assert application.rule_snapshot["version"] == rule_set.version
        assert application.facts_snapshot["cgpa"] == 8.4

        profile = await db.scalar(
            select(StudentProfile).where(StudentProfile.user_id == student.id)
        )
        assert profile is not None
        profile.education = [{**profile.education[0], "score": 6.0}]
        await db.commit()
        response = await response_for_application(db, application)
        assert response.facts_snapshot["cgpa"] == 8.4
        assert response.resume_snapshot["checksum"] == "checksum-one"


@pytest.mark.asyncio
async def test_student_can_track_withdraw_and_appeal_without_losing_history() -> None:
    async with TestSession() as db:
        institution, admin, student = await seed_people(db, "lifecycle")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        assert resume is not None
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "application-lifecycle-001",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        first, replayed = await create_application_appeal(
            db,
            institution.id,
            student.id,
            application.id,
            "appeal-lifecycle-001",
            ApplicationAppealCreate(
                kind="manual_review",
                reason="Please review the equivalent coursework attached to my profile.",
                supporting_evidence=["Reviewed education record in profile"],
                confirmation="SUBMIT APPEAL",
            ),
        )
        replay, was_replayed = await create_application_appeal(
            db,
            institution.id,
            student.id,
            application.id,
            "appeal-lifecycle-001",
            ApplicationAppealCreate(
                kind="manual_review",
                reason="Please review the equivalent coursework attached to my profile.",
                supporting_evidence=["Reviewed education record in profile"],
                confirmation="SUBMIT APPEAL",
            ),
        )
        assert not replayed
        assert was_replayed
        assert replay.id == first.id
        resolved = await resolve_application_appeal(
            db,
            institution.id,
            admin.id,
            first.id,
            ApplicationAppealResolution(
                status="approved",
                administrator_response=(
                    "The evidence was reviewed and accepted for this application."
                ),
            ),
        )
        assert resolved.resolved_by_user_id == admin.id

        withdrawn, withdrawal_replayed = await withdraw_application(
            db,
            institution.id,
            student.id,
            application.id,
            ApplicationWithdrawal(
                reason="I accepted another placement opportunity.",
                confirmation="WITHDRAW",
            ),
        )
        replayed_withdrawal, second_withdrawal_replay = await withdraw_application(
            db,
            institution.id,
            student.id,
            application.id,
            ApplicationWithdrawal(
                reason="I accepted another placement opportunity.",
                confirmation="WITHDRAW",
            ),
        )
        assert not withdrawal_replayed
        assert second_withdrawal_replay
        assert replayed_withdrawal.id == withdrawn.id
        response = await get_student_application(db, institution.id, student.id, application.id)
        assert response.status == "withdrawn"
        assert response.withdrawn_at is not None
        assert response.can_withdraw is False
        assert [event.to_status for event in response.history] == ["submitted", "withdrawn"]
        assert response.appeals[0].status == "approved"
        assert response.appeals[0].administrator_response is not None
        calendar = application_deadline_calendar(application)
        assert "BEGIN:VCALENDAR\r\n" in calendar
        assert "Software Engineer application deadline" in calendar
        assert "DTSTART:" in calendar


@pytest.mark.asyncio
async def test_student_application_detail_is_default_deny_across_tenants() -> None:
    async with TestSession() as db:
        institution, admin, student = await seed_people(db, "owned-detail")
        other, _, outsider = await seed_people(db, "outsider-detail")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        assert resume is not None
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "application-owned-detail-001",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        with pytest.raises(RecruitmentError, match="application_not_found"):
            await get_student_application(db, other.id, outsider.id, application.id)


@pytest.mark.asyncio
async def test_admin_transition_and_reasoned_override_are_append_only() -> None:
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        assert resume is not None
        application, _ = await create_application(
            db,
            institution.id,
            student.id,
            "application-key-002",
            ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
        )
        await update_application_status(
            db,
            institution.id,
            application.id,
            admin.id,
            ApplicationStatusUpdate(status="under_review", reason="Initial evidence review"),
        )
        await override_application(
            db,
            institution.id,
            application.id,
            admin.id,
            ApplicationOverrideCreate(
                status="shortlisted",
                reason="Policy permits documented course-equivalence evidence.",
                policy_reference="Placement Policy §4.2",
            ),
        )
        await db.commit()
        page = await list_admin_applications(
            db, institution.id, role.id, None, page=1, page_size=25
        )
        response = page.items[0]
        assert response.status == "shortlisted"
        assert [item.to_status for item in response.history] == [
            "submitted",
            "under_review",
            "shortlisted",
        ]
        assert response.overrides[0].policy_reference == "Placement Policy §4.2"


@pytest.mark.asyncio
async def test_recruitment_queries_default_deny_across_institutions() -> None:
    async with TestSession() as db:
        first, admin, _ = await seed_people(db, "first")
        second, _, student_two = await seed_people(db, "second")
        role, _ = await publish_sample_role(db, first, admin, include_missing_rule=False)
        results = await list_opportunities(
            db,
            second.id,
            student_two.id,
            query=None,
            location=None,
            work_mode=None,
            skill=None,
            saved_only=False,
            page=1,
            page_size=20,
        )
        assert results.items == []
        with pytest.raises(RecruitmentError, match="role_not_found"):
            await create_rule_set(
                db,
                second.id,
                role.id,
                student_two.id,
                RuleSetCreate(
                    rules=[
                        {
                            "field": "degree",
                            "operator": "eq",
                            "value": "B.Tech",
                            "label": "Degree",
                        }
                    ]
                ),
            )


@pytest.mark.asyncio
async def test_tenant_context_is_derived_from_the_authenticated_principal() -> None:
    async with TestSession() as db:
        institution, _, student = await seed_people(db, "tenant-context")
    principal = AuthenticatedPrincipal(
        user=student,
        session=Session(
            user_id=student.id,
            token_hash=hash_secret("tenant-context-session"),
            csrf_hash=hash_secret("tenant-context-csrf"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_activity_at=datetime.now(UTC),
        ),
        membership=None,
    )

    tenant = await get_tenant_context(principal)

    assert tenant.institution_id == institution.id
    assert tenant.user_id == student.id
    assert tenant.role == UserRole.STUDENT.value


@pytest.mark.asyncio
async def test_closed_or_ineligible_roles_reject_new_applications() -> None:
    async with TestSession() as db:
        institution, admin, student = await seed_people(db)
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)
        resume = await db.scalar(select(ResumeVersion).where(ResumeVersion.user_id == student.id))
        assert resume is not None
        drive_id = role.drive_id
        await transition_drive(db, institution.id, drive_id, "close")
        await db.commit()
        with pytest.raises(RecruitmentError, match="opportunity_not_found"):
            await create_application(
                db,
                institution.id,
                student.id,
                "application-key-003",
                ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
            )


@pytest.mark.asyncio
async def test_http_contract_enforces_roles_and_connects_publication_to_application() -> None:
    async with TestSession() as setup_db:
        institution, admin, student = await seed_people(setup_db, "api")
        resume = await setup_db.scalar(
            select(ResumeVersion).where(ResumeVersion.user_id == student.id)
        )
        assert resume is not None

    principal = AuthenticatedPrincipal(
        user=admin,
        session=Session(
            user_id=admin.id,
            token_hash=hash_secret("admin-session-token"),
            csrf_hash=hash_secret("admin-csrf-token"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_activity_at=datetime.now(UTC),
        ),
        membership=None,
    )

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with TestSession() as session:
            yield session

    async def override_principal() -> AuthenticatedPrincipal:
        return principal

    def skip_csrf() -> None:
        return None

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_principal] = override_principal
    app.dependency_overrides[verify_authenticated_csrf] = skip_csrf
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            company = await client.post(
                "/api/v1/admin/recruitment/companies",
                json={"name": "Contour Software", "website_url": "https://example.com"},
            )
            assert company.status_code == 201, company.text
            now = datetime.now(UTC)
            drive = await client.post(
                "/api/v1/admin/recruitment/drives",
                json={
                    "company_id": company.json()["id"],
                    "title": "API Engineering Drive",
                    "description": "A complete integration fixture for placement operations.",
                    "location": "Pune, India",
                    "work_mode": "hybrid",
                    "opens_at": (now - timedelta(hours=1)).isoformat(),
                    "deadline_at": (now + timedelta(days=5)).isoformat(),
                },
            )
            assert drive.status_code == 201, drive.text
            role = await client.post(
                f"/api/v1/admin/recruitment/drives/{drive.json()['id']}/roles",
                json={
                    "title": "Frontend Developer",
                    "description": (
                        "Build accessible student-facing software with reviewed evidence."
                    ),
                    "employment_type": "full-time",
                    "location": "Pune, India",
                    "work_mode": "hybrid",
                    "skills": ["React"],
                    "requirements": ["B.Tech"],
                },
            )
            assert role.status_code == 201, role.text
            rule_set = await client.post(
                f"/api/v1/admin/recruitment/roles/{role.json()['id']}/rule-sets",
                json={
                    "rules": [
                        {
                            "field": "degree",
                            "operator": "eq",
                            "value": "B.Tech",
                            "label": "Program eligibility",
                        }
                    ]
                },
            )
            assert rule_set.status_code == 201, rule_set.text
            assert (
                await client.post(
                    f"/api/v1/admin/recruitment/roles/{role.json()['id']}/rule-sets/"
                    f"{rule_set.json()['id']}/publish"
                )
            ).status_code == 200
            assert (
                await client.post(f"/api/v1/admin/recruitment/roles/{role.json()['id']}/publish")
            ).status_code == 200
            assert (
                await client.post(
                    f"/api/v1/admin/recruitment/drives/{drive.json()['id']}/actions/publish"
                )
            ).status_code == 200

            principal = AuthenticatedPrincipal(
                user=student,
                session=Session(
                    user_id=student.id,
                    token_hash=hash_secret("student-session-token"),
                    csrf_hash=hash_secret("student-csrf-token"),
                    expires_at=now + timedelta(hours=1),
                    last_activity_at=now,
                ),
                membership=None,
            )
            opportunities = await client.get("/api/v1/opportunities")
            assert opportunities.status_code == 200, opportunities.text
            assert opportunities.json()["items"][0]["eligibility"]["status"] == "eligible"
            forbidden = await client.get("/api/v1/admin/recruitment/companies")
            assert forbidden.status_code == 403
            applied = await client.post(
                "/api/v1/applications",
                headers={"Idempotency-Key": "api-application-001"},
                json={"role_id": role.json()["id"], "resume_version_id": str(resume.id)},
            )
            assert applied.status_code == 201, applied.text
            replayed = await client.post(
                "/api/v1/applications",
                headers={"Idempotency-Key": "api-application-001"},
                json={"role_id": role.json()["id"], "resume_version_id": str(resume.id)},
            )
            assert replayed.status_code == 200
            assert replayed.json()["id"] == applied.json()["id"]
    finally:
        app.dependency_overrides.clear()
