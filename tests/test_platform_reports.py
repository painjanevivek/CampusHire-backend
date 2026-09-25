from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.models.auth import Institution, InstitutionMembership, MembershipStatus, User, UserRole
from app.models.profile import StudentProfile
from app.models.recruitment import Application, Company, PlacementDrive, PlacementRole
from app.modules.auth.security import hash_password
from tests.test_auth import (  # noqa: F401
    TestSession,
    client,
    database,
    seed_platform_admin,
    sign_in,
)

pytestmark = pytest.mark.asyncio


async def seed_report() -> tuple[list[Institution], list[UUID], User]:
    async with TestSession() as db:
        colleges: list[Institution] = []
        application_ids: list[UUID] = []
        officer: User | None = None
        for index, (code, name) in enumerate((("PCCOE", "PCCOE"), ("PCU", "PCU"))):
            college = Institution(code=code, name=name)
            db.add(college)
            await db.flush()
            student = User(
                institution_id=college.id,
                email=f"student{index}@example.edu",
                password_hash=hash_password("a student passphrase"),
                role=UserRole.STUDENT.value,
            )
            if index == 0:
                officer = User(
                    institution_id=college.id,
                    email="officer@example.edu",
                    username="officer",
                    password_hash=hash_password("an officer passphrase"),
                    role=UserRole.TNP_ADMIN.value,
                )
                db.add(officer)
            db.add(student)
            await db.flush()
            if officer and index == 0:
                db.add(
                    InstitutionMembership(
                        institution_id=college.id,
                        user_id=officer.id,
                        role=UserRole.TNP_ADMIN.value,
                        status=MembershipStatus.ACTIVE.value,
                    )
                )
            db.add(
                StudentProfile(
                    user_id=student.id,
                    institution_id=college.id,
                    full_name=("=Asha" if index == 0 else "Dev Shah"),
                    prn=f"124B1B28{index}",
                    prn_verified_at=datetime.now(UTC),
                )
            )
            company = Company(institution_id=college.id, name="NVIDIA")
            db.add(company)
            await db.flush()
            drive = PlacementDrive(
                institution_id=college.id,
                company_id=company.id,
                title="Graduate Engineer",
                description="Synthetic drive",
                location="Pune",
                work_mode="onsite",
                opens_at=datetime(2026, 9, 1, tzinfo=UTC),
                deadline_at=datetime.now(UTC) + timedelta(days=30),
                status="published",
            )
            db.add(drive)
            await db.flush()
            role = PlacementRole(
                institution_id=college.id,
                drive_id=drive.id,
                title="Software Engineer",
                description="Synthetic role",
                employment_type="full_time",
                location="Pune",
                work_mode="onsite",
                status="published",
            )
            db.add(role)
            await db.flush()
            application = Application(
                institution_id=college.id,
                role_id=role.id,
                student_user_id=student.id,
                resume_version_id=uuid4(),
                eligibility_evaluation_id=uuid4(),
                idempotency_key=f"report-{index}",
                status="submitted",
                role_snapshot={"title": role.title},
                resume_snapshot={"version": 1},
                facts_snapshot={"cgpa": 8.5},
                rule_snapshot={},
                eligibility_snapshot={"eligible": True},
                profile_snapshot={"full_name": "=Asha" if index == 0 else "Dev Shah"},
                application_form_snapshot={"version": 1},
                acknowledgment_snapshot={"confirmed": True},
            )
            db.add(application)
            await db.flush()
            colleges.append(college)
            application_ids.append(application.id)
        await db.commit()
        assert officer is not None
        return colleges, application_ids, officer


async def test_drive_report_groups_colleges_and_exports_scoped_applicants(
    client: TestClient,  # noqa: F811
) -> None:
    await seed_platform_admin()
    colleges, application_ids, _ = await seed_report()
    sign_in(client, "platform-admin", "a secure platform passphrase")

    groups = client.get("/api/v1/platform/reports/drive-groups")
    assert groups.status_code == 200, groups.text
    group = groups.json()["items"][0]
    assert (group["company_name"], group["drive_title"], group["cycle_year"]) == (
        "NVIDIA",
        "Graduate Engineer",
        2026,
    )
    assert group["drive_count"] == 2
    assert group["student_count"] == group["application_count"] == 2
    assert {item["institution_name"] for item in group["institutions"]} == {"PCCOE", "PCU"}
    pccoe_breakdown = next(
        item for item in group["institutions"] if item["institution_name"] == "PCCOE"
    )
    assert pccoe_breakdown["drives"][0]["id"] == pccoe_breakdown["drive_ids"][0]
    scoped_groups = client.get(
        "/api/v1/platform/reports/drive-groups",
        params={"institution_id": str(colleges[0].id)},
    )
    assert scoped_groups.status_code == 200
    assert scoped_groups.json()["items"][0]["drive_count"] == 1
    assert scoped_groups.json()["items"][0]["student_count"] == 1

    params = {"company_name": "NVIDIA", "drive_title": "Graduate Engineer", "cycle_year": 2026}
    applicants = client.get("/api/v1/platform/reports/drive-applicants", params=params)
    assert applicants.status_code == 200, applicants.text
    assert applicants.json()["total"] == 2
    assert {item["prn"] for item in applicants.json()["items"]} == {
        "124B1B280",
        "124B1B281",
    }
    scoped = client.get(
        "/api/v1/platform/reports/drive-applicants",
        params={**params, "institution_id": str(colleges[0].id)},
    )
    assert scoped.json()["total"] == 1
    assert scoped.json()["items"][0]["institution_id"] == str(colleges[0].id)

    evidence = client.get(f"/api/v1/platform/reports/applications/{application_ids[0]}")
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["applicant"]["prn"] == "124B1B280"
    assert evidence.json()["profile_snapshot"]["full_name"] == "=Asha"
    assert evidence.json()["facts_snapshot"] == {"cgpa": 8.5}
    assert "encrypted_payload" not in evidence.text

    full_csv = client.get("/api/v1/platform/reports/drive-applicants.csv", params=params)
    assert full_csv.status_code == 200, full_csv.text
    assert "124B1B280" in full_csv.text and "124B1B281" in full_csv.text
    assert "'=Asha" in full_csv.text
    scoped_csv = client.get(
        "/api/v1/platform/reports/drive-applicants.csv",
        params={**params, "institution_id": str(colleges[0].id)},
    )
    assert scoped_csv.status_code == 200, scoped_csv.text
    assert "124B1B280" in scoped_csv.text and "124B1B281" not in scoped_csv.text
    drive_csv = client.get(
        "/api/v1/platform/reports/drive-applicants.csv",
        params={
            **params,
            "institution_id": str(colleges[0].id),
            "drive_id": pccoe_breakdown["drive_ids"][0],
        },
    )
    assert drive_csv.status_code == 200, drive_csv.text
    assert "124B1B280" in drive_csv.text and "124B1B281" not in drive_csv.text
    wrong_scope = client.get(
        "/api/v1/platform/reports/drive-applicants",
        params={
            **params,
            "institution_id": str(colleges[1].id),
            "drive_id": pccoe_breakdown["drive_ids"][0],
        },
    )
    assert wrong_scope.status_code == 200
    assert wrong_scope.json()["total"] == 0
    assert client.get(f"/api/v1/platform/reports/applications/{uuid4()}").status_code == 404

    client.cookies.clear()
    sign_in(client, "officer", "an officer passphrase")
    assert client.get("/api/v1/platform/reports/drive-groups").status_code == 403
    assert client.get("/api/v1/platform/reports/drive-applicants", params=params).status_code == 403
    denied_csv = client.get("/api/v1/platform/reports/drive-applicants.csv", params=params)
    assert denied_csv.status_code == 403
    client.cookies.clear()
    sign_in(client, "student0@example.edu", "a student passphrase")
    assert client.get("/api/v1/platform/reports/drive-groups").status_code == 403
