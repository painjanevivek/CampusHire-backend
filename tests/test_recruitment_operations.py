from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.auth import Institution, Session, User, UserRole
from app.models.intelligence import PolicyDocument, ReviewStatus
from app.models.profile import StudentProfile
from app.models.recruitment import PlacementDrive
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
    BulkApplicationStatusRequest,
    CompanyCreate,
    DriveCreate,
    DriveUpdate,
    RoleCreate,
    RuleSetCreate,
)
from app.modules.recruitment.service import (
    RecruitmentError,
    application_deadline_calendar,
    apply_bulk_application_status,
    create_application,
    create_application_appeal,
    create_company,
    create_drive,
    create_role,
    create_rule_set,
    delete_drive,
    duplicate_drive,
    get_student_application,
    list_admin_applications,
    list_opportunities,
    list_roles,
    override_application,
    preview_bulk_application_status,
    preview_role_eligibility,
    publish_role,
    publish_rule_set,
    resolve_application_appeal,
    response_for_application,
    transition_drive,
    update_application_status,
    update_drive,
    withdraw_application,
)
from app.modules.resumes.builder import ResumeContent, generate_pdf
from app.modules.resumes.workflow import ResumeWorkflowError, delete_owned_version


class StorageMustNotBeCalled:
    def delete(self, key: str) -> None:
        raise AssertionError(f"locked storage object was deleted: {key}")


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
    policy_ids: list[UUID] | None = None,
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
        db,
        institution.id,
        role.id,
        admin.id,
        RuleSetCreate(rules=rules, policy_ids=policy_ids or []),
    )
    await publish_rule_set(db, institution.id, role.id, rule_set.id)
    await publish_role(db, institution.id, role.id)
    await transition_drive(db, institution.id, drive.id, "publish")
    await db.commit()
    return role, rule_set


@pytest.mark.asyncio
async def test_drive_duplication_is_draft_and_rule_preview_is_deterministic() -> None:
    async with TestSession() as db:
        institution, admin, _ = await seed_people(db, "duplicate")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=True)

        preview = await preview_role_eligibility(
            db,
            institution.id,
            role.id,
            {
                "degree": "B.Tech",
                "cgpa": 8.2,
                "active_backlogs": None,
            },
        )
        assert preview.status == "needs_manual_review"
        assert preview.missing_evidence == ["Active backlogs"]

        duplicate = await duplicate_drive(
            db,
            institution.id,
            role.drive_id,
            admin.id,
        )
        assert duplicate.status == "draft"
        assert duplicate.title.endswith("— copy")
        cloned_roles = await list_roles(db, institution.id, duplicate.id)
        assert len(cloned_roles) == 1
        assert cloned_roles[0].status == "draft"


@pytest.mark.asyncio
async def test_draft_drive_can_be_edited_and_deleted_only_inside_its_tenant() -> None:
    async with TestSession() as db:
        institution, _, _ = await seed_people(db, "draft-owner")
        other_institution, _, _ = await seed_people(db, "draft-other")
        company = await create_company(
            db,
            institution.id,
            CompanyCreate(name="Draft Company", website_url="https://example.com"),
        )
        other_company = await create_company(
            db,
            other_institution.id,
            CompanyCreate(name="Other Tenant Company", website_url="https://example.org"),
        )
        drive = await create_drive(
            db,
            institution.id,
            DriveCreate(
                company_id=company.id,
                title="Original draft title",
                description="A private draft that has not been published to students.",
                location="Pune, India",
                work_mode="hybrid",
                opens_at=datetime.now(UTC),
                deadline_at=datetime.now(UTC) + timedelta(days=7),
            ),
        )

        with pytest.raises(RecruitmentError, match="drive_not_found"):
            await delete_drive(db, other_institution.id, drive.id)
        with pytest.raises(RecruitmentError, match="company_not_found"):
            await update_drive(
                db,
                institution.id,
                drive.id,
                DriveUpdate(company_id=other_company.id),
            )

        updated = await update_drive(
            db,
            institution.id,
            drive.id,
            DriveUpdate(title="Updated draft title", work_mode="remote"),
        )
        assert updated.title == "Updated draft title"
        assert updated.work_mode == "remote"

        deleted = await delete_drive(db, institution.id, drive.id)
        assert deleted.id == drive.id
        assert await db.get(PlacementDrive, drive.id) is None


@pytest.mark.asyncio
async def test_published_drive_cannot_be_deleted() -> None:
    async with TestSession() as db:
        institution, admin, _ = await seed_people(db, "published-delete")
        role, _ = await publish_sample_role(db, institution, admin, include_missing_rule=False)

        with pytest.raises(RecruitmentError, match="published_drive_is_immutable"):
            await delete_drive(db, institution.id, role.drive_id)

        assert await db.get(PlacementDrive, role.drive_id) is not None


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
        policy = PolicyDocument(
            institution_id=institution.id,
            title="Placement eligibility policy",
            version=2,
            source_reference="approved-policy-2026-v2.pdf",
            sections=[{"section": "Eligibility", "page": 3, "text": "Reviewed criteria"}],
            status=ReviewStatus.APPROVED.value,
            created_by_user_id=admin.id,
            reviewed_by_user_id=admin.id,
            review_reason="Approved by the placement policy owner.",
            approved_at=datetime.now(UTC),
        )
        db.add(policy)
        await db.flush()
        role, rule_set = await publish_sample_role(
            db,
            institution,
            admin,
            include_missing_rule=False,
            policy_ids=[policy.id],
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
        assert application.rule_snapshot["policy_references"] == [
            {
                "id": str(policy.id),
                "title": policy.title,
                "version": policy.version,
                "source_reference": policy.source_reference,
                "approved_at": policy.approved_at.isoformat(),
            }
        ]
        assert application.facts_snapshot["cgpa"] == 8.4

        policy.status = ReviewStatus.RETIRED.value
        await db.flush()
        assert application.rule_snapshot["policy_references"][0]["version"] == 2

        profile = await db.scalar(
            select(StudentProfile).where(StudentProfile.user_id == student.id)
        )
        assert profile is not None
        profile.education = [{**profile.education[0], "score": 6.0}]
        await db.commit()
        response = await response_for_application(db, application)
        assert response.facts_snapshot["cgpa"] == 8.4
        assert response.resume_snapshot["checksum"] == "checksum-one"
        bulk_payload = BulkApplicationStatusRequest(
            application_ids=[application.id],
            status="under_review",
            reason="Reviewed against the published eligibility evidence.",
        )
        preview = await preview_bulk_application_status(db, institution.id, bulk_payload)
        assert preview.allowed_count == 1
        assert preview.blocked_count == 0
        updated = await apply_bulk_application_status(db, institution.id, admin.id, bulk_payload)
        assert updated[0].status == "under_review"
        with pytest.raises(ResumeWorkflowError, match="resume_version_locked_by_application"):
            await delete_owned_version(
                db,
                user_id=student.id,
                version_id=resume.id,
                store=StorageMustNotBeCalled(),  # type: ignore[arg-type]
            )


@pytest.mark.asyncio
async def test_rule_policy_references_default_deny_other_institutions() -> None:
    async with TestSession() as db:
        institution, admin, _ = await seed_people(db, "policy-owner")
        other_institution, other_admin, _ = await seed_people(db, "policy-other")
        role, _ = await publish_sample_role(
            db, institution, admin, include_missing_rule=False
        )
        foreign_policy = PolicyDocument(
            institution_id=other_institution.id,
            title="Other institution policy",
            version=1,
            source_reference="other-policy.pdf",
            sections=[],
            status=ReviewStatus.APPROVED.value,
            created_by_user_id=other_admin.id,
            reviewed_by_user_id=other_admin.id,
            review_reason="Approved for another institution.",
            approved_at=datetime.now(UTC),
        )
        db.add(foreign_policy)
        await db.flush()

        with pytest.raises(RecruitmentError, match="approved_policy_reference_not_found"):
            await create_rule_set(
                db,
                institution.id,
                role.id,
                admin.id,
                RuleSetCreate(
                    rules=[
                        {
                            "field": "degree",
                            "operator": "eq",
                            "value": "B.Tech",
                            "label": "Degree",
                        }
                    ],
                    policy_ids=[foreign_policy.id],
                ),
            )


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
            mfa_verified_at=datetime.now(UTC),
        ),
        membership=None,
    )
    admin_principal = principal

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
            throwaway = await client.post(
                "/api/v1/admin/recruitment/drives",
                json={
                    "company_id": company.json()["id"],
                    "title": "Discardable API Draft",
                    "description": "A draft used to verify the edit and delete contract.",
                    "location": "Pune, India",
                    "work_mode": "hybrid",
                    "opens_at": now.isoformat(),
                    "deadline_at": (now + timedelta(days=2)).isoformat(),
                },
            )
            assert throwaway.status_code == 201, throwaway.text
            throwaway_id = throwaway.json()["id"]
            edited = await client.patch(
                f"/api/v1/admin/recruitment/drives/{throwaway_id}",
                json={"title": "Updated discardable API draft"},
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["title"] == "Updated discardable API draft"
            removed = await client.delete(
                f"/api/v1/admin/recruitment/drives/{throwaway_id}"
            )
            assert removed.status_code == 204, removed.text
            remaining_drives = await client.get("/api/v1/admin/recruitment/drives")
            assert throwaway_id not in {item["id"] for item in remaining_drives.json()}

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
            principal = admin_principal
            under_review = await client.post(
                f"/api/v1/admin/recruitment/applications/{applied.json()['id']}/status",
                json={
                    "status": "under_review",
                    "reason": "The placement reviewer started the documented evidence review.",
                },
            )
            assert under_review.status_code == 200, under_review.text
            missing_policy = await client.post(
                f"/api/v1/admin/recruitment/applications/{applied.json()['id']}/override",
                json={
                    "status": "shortlisted",
                    "reason": "The published equivalence policy supports this reviewed exception.",
                },
            )
            assert missing_policy.status_code == 422

            principal = AuthenticatedPrincipal(
                user=admin,
                session=Session(
                    user_id=admin.id,
                    token_hash=hash_secret("stale-admin-session-token"),
                    csrf_hash=hash_secret("stale-admin-csrf-token"),
                    expires_at=now + timedelta(hours=1),
                    last_activity_at=now,
                    mfa_verified_at=now - timedelta(minutes=11),
                ),
                membership=None,
            )
            stale_override = await client.post(
                f"/api/v1/admin/recruitment/applications/{applied.json()['id']}/override",
                json={
                    "status": "shortlisted",
                    "reason": "The published equivalence policy supports this reviewed exception.",
                    "policy_reference": "Placement Policy section 4.2",
                },
            )
            assert stale_override.status_code == 403
            assert stale_override.json()["error"]["code"] == "reauthentication_required"

            principal = admin_principal
            overridden = await client.post(
                f"/api/v1/admin/recruitment/applications/{applied.json()['id']}/override",
                json={
                    "status": "shortlisted",
                    "reason": "The published equivalence policy supports this reviewed exception.",
                    "policy_reference": "Placement Policy section 4.2",
                },
            )
            assert overridden.status_code == 200, overridden.text
            assert overridden.json()["overrides"][0]["policy_reference"] == (
                "Placement Policy section 4.2"
            )
            immutable_delete = await client.delete(
                f"/api/v1/admin/recruitment/drives/{drive.json()['id']}"
            )
            assert immutable_delete.status_code == 409
    finally:
        app.dependency_overrides.clear()
