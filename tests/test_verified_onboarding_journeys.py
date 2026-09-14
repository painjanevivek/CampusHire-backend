from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import rate_limit
from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.auth import (
    Institution,
    InstitutionDomain,
    InstitutionRegistrationRequest,
    MembershipInvitation,
    StudentRegistrationRequest,
    UserRole,
)
from app.models.profile import StudentProfile
from app.modules.auth import registration as registration_service
from app.modules.auth.security import hash_secret, totp_code
from app.modules.institutions import lifecycle as institution_lifecycle

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(engine, expire_on_commit=False)


async def override_db() -> AsyncIterator[AsyncSession]:
    async with TestSession() as session:
        yield session


@pytest.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    rate_limit._fallback.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app.dependency_overrides[get_db] = override_db
    yield
    app.dependency_overrides.clear()
    rate_limit._fallback.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 204
    return {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": client.cookies[get_settings().csrf_cookie_name],
    }


def save_step(
    client: TestClient, path: str, state: dict[str, object], **payload: object
) -> dict[str, object]:
    response = client.put(
        path,
        headers=csrf_headers(client),
        json={"expected_revision": state["revision"], **payload},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_student_signup_activation_and_onboarding_journey(client: TestClient) -> None:
    activation_token = "student-activation-token"  # noqa: S105
    async with TestSession() as db:
        institution = Institution(code="student-campus", name="Student Campus", is_active=True)
        db.add(institution)
        await db.flush()
        db.add_all(
            [
                InstitutionDomain(
                    institution_id=institution.id,
                    domain="student-campus.edu",
                    verification_status="verified",
                    verified_at=datetime.now(UTC),
                ),
                MembershipInvitation(
                    institution_id=institution.id,
                    email="student@student-campus.edu",
                    role=UserRole.STUDENT.value,
                    token_hash=hash_secret(activation_token),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
            ]
        )
        await db.commit()

    started = client.post(
        "/api/v1/auth/signup",
        headers=csrf_headers(client),
        json={
            "name": "Student",
            "surname": "One",
            "dob": "2004-05-16",
            "email": "student@student-campus.edu",
            "password": "a secure student passphrase",
            "re_enter_password": "a secure student passphrase",
            "invitation_code": activation_token,
        },
    )
    assert started.status_code == 202, started.text
    assert started.json()["next_path"] == f"/activate/{activation_token}"

    invitation_state = client.get(f"/api/v1/auth/invitations/{activation_token}")
    assert invitation_state.status_code == 200
    assert invitation_state.json()["student_signup_ready"] is True

    mismatched_password = client.post(
        f"/api/v1/auth/invitations/{activation_token}/accept",
        headers=csrf_headers(client),
        json={
            "password": "a different student passphrase",
            "terms_version": "2026-08-28",
            "privacy_version": "2026-08-28",
        },
    )
    assert mismatched_password.status_code == 422

    activated = client.post(
        f"/api/v1/auth/invitations/{activation_token}/accept",
        headers=csrf_headers(client),
        json={
            "password": "a secure student passphrase",
            "terms_version": "2026-08-28",
            "privacy_version": "2026-08-28",
        },
    )
    assert activated.status_code == 201, activated.text
    assert activated.json()["role"] == UserRole.STUDENT.value

    async with TestSession() as db:
        registration = await db.scalar(select(StudentRegistrationRequest))
        profile = await db.scalar(select(StudentProfile))
        assert registration is not None and registration.password_hash is None
        assert registration.status == "activated"
        assert profile is not None
        assert profile.full_name == "Student One"
        assert str(profile.date_of_birth) == "2004-05-16"

    loaded = client.get("/api/v1/onboarding")
    assert loaded.status_code == 200, loaded.text
    state = loaded.json()
    steps = [
        {
            "step": 1,
            "identity": {
                "full_name": "Student One",
                "prn": "PRN-001",
                "department": "Computer Science",
                "graduation_year": 2027,
            },
        },
        {
            "step": 2,
            "education": [
                {
                    "qualification_level": "degree",
                    "degree": "B.Tech",
                    "branch": "Computer Science",
                    "institution": "Student Campus",
                    "start_year": 2023,
                    "graduation_year": 2027,
                    "score": 8.4,
                    "score_scale": "cgpa_10",
                    "active_backlogs": 0,
                }
            ],
        },
        {"step": 3, "experience": []},
        {
            "step": 4,
            "projects_skills": {"projects": [], "skills": ["Python"], "certifications": []},
        },
        {
            "step": 5,
            "career_preferences": {
                "target_roles": ["Software Engineer"],
                "industries": ["Technology"],
                "locations": ["Pune"],
                "job_types": ["full_time"],
                "work_modes": ["hybrid"],
            },
        },
        {
            "step": 6,
            "placement_participation": {
                "placement_cycle": "2026-27",
                "communication_channels": ["email"],
                "visibility": "placement_team",
                "privacy_accepted": True,
            },
        },
        {"step": 7, "review": {"confirmed": True}},
    ]
    for step in steps:
        state = save_step(client, "/api/v1/onboarding/step", state, **step)

    assert state["completed"] is True
    assert state["current_step"] == 7
    assert state["identity"]["full_name"] == "Student One"  # type: ignore[index]


async def test_tnp_registration_verification_approval_and_onboarding_journey(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    verification_token = "institution-verification-token"  # noqa: S105
    owner_token = "institution-owner-activation-token"  # noqa: S105
    operator_key = "test-operator-bootstrap-key"
    monkeypatch.setattr(registration_service, "new_secret", lambda: verification_token)
    monkeypatch.setattr(institution_lifecycle, "new_secret", lambda: owner_token)
    monkeypatch.setenv("OPERATOR_BOOTSTRAP_KEY", operator_key)
    get_settings.cache_clear()

    started = client.post(
        "/api/v1/auth/institution-registrations",
        headers=csrf_headers(client),
        json={
            "institution_name": "Verified Institute",
            "institution_code": "verified-institute",
            "institutional_email": "owner@verified.edu",
            "domain": "verified.edu",
        },
    )
    assert started.status_code == 202, started.text

    verified = client.post(
        "/api/v1/auth/institution-registrations/verify",
        headers=csrf_headers(client),
        json={"token": verification_token},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "pending_approval"

    approved = client.post(
        f"/api/v1/operator/institution-registration-requests/{started.json()['request_id']}/decision",
        headers={"X-Operator-Key": operator_key},
        json={"decision": "approve"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    activated = client.post(
        f"/api/v1/auth/invitations/{owner_token}/accept",
        headers=csrf_headers(client),
        json={
            "password": "a secure institution owner passphrase",
            "terms_version": "2026-08-28",
            "privacy_version": "2026-08-28",
        },
    )
    assert activated.status_code == 201, activated.text
    assert activated.json()["role"] == UserRole.TNP_OWNER.value

    setup = client.post("/api/v1/auth/mfa/setup", headers=csrf_headers(client))
    assert setup.status_code == 200, setup.text
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=csrf_headers(client),
        json={"code": totp_code(setup.json()["secret"])},
    )
    assert confirmed.status_code == 200, confirmed.text

    loaded = client.get("/api/v1/admin/onboarding")
    assert loaded.status_code == 200, loaded.text
    state = loaded.json()
    assert state["institution_active"] is False
    steps = [
        {"step": 1, "administrator": {"administrator_name": "Placement Owner"}},
        {
            "step": 2,
            "institution": {"official_name": "Verified Institute", "domain": "verified.edu"},
        },
        {
            "step": 3,
            "campuses": [
                {
                    "name": "Main Campus",
                    "programs": [
                        {
                            "name": "Engineering",
                            "branches": ["Computer Science"],
                            "graduating_batches": [2027],
                        }
                    ],
                }
            ],
        },
        {
            "step": 4,
            "placement_cycle": {
                "name": "2026-27",
                "starts_on": "2026-09-01",
                "ends_on": "2027-06-30",
                "participating_cohorts": ["2027"],
            },
        },
        {
            "step": 5,
            "roster": {"roster_import_id": None, "invitation_mode": "roster_and_verified_domain"},
        },
        {
            "step": 6,
            "policies": {
                "eligibility_template_names": [],
                "policy_names": [],
                "approval_roles": ["tnp_owner", "tnp_admin"],
            },
        },
        {"step": 7, "review": {"invite_team_emails": [], "activate_institution": True}},
    ]
    for step in steps:
        state = save_step(client, "/api/v1/admin/onboarding/step", state, **step)

    assert state["institution_active"] is True
    assert state["completed_steps"] == [1, 2, 3, 4, 5, 6, 7]
    async with TestSession() as db:
        request = await db.scalar(select(InstitutionRegistrationRequest))
        assert request is not None
        institution = await db.get(Institution, request.institution_id)
        assert institution is not None and institution.is_active is True

    get_settings.cache_clear()
