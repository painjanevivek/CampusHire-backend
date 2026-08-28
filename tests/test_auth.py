from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.auth import (
    AuditEvent,
    Institution,
    InstitutionMembership,
    MembershipInvitation,
    MembershipStatus,
    User,
    UserRole,
)
from app.modules.auth.security import hash_password, hash_secret, totp_code

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
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app.dependency_overrides[get_db] = override_db
    yield
    app.dependency_overrides.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def csrf_headers(client: TestClient) -> dict[str, str]:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 204
    token = client.cookies[get_settings().csrf_cookie_name]
    return {"Origin": "http://localhost:3000", "X-CSRF-Token": token}


async def signup(client: TestClient) -> dict[str, str]:
    token = "test-invitation-token"  # noqa: S105
    async with TestSession() as db:
        institution = Institution(code="student-campus", name="Student Campus")
        db.add(institution)
        await db.flush()
        db.add(
            MembershipInvitation(
                institution_id=institution.id,
                email="student@example.edu",
                role=UserRole.STUDENT.value,
                token_hash=hash_secret(token),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        await db.commit()
    response = client.post(
        f"/api/v1/auth/invitations/{token}/accept",
        headers=csrf_headers(client),
        json={
            "password": "a long campus passphrase",
            "terms_version": "2026-08-28",
            "privacy_version": "2026-08-28",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_signup_requires_an_invitation(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        headers=csrf_headers(client),
        json={"email": "student@example.edu", "password": "a long campus passphrase"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invitation_required"


async def test_invitation_acceptance_normalizes_email_and_creates_student_session(
    client: TestClient,
) -> None:
    payload = await signup(client)
    assert payload["email"] == "student@example.edu"
    assert payload["role"] == "student"
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == payload["id"]


async def test_invitation_is_single_use(client: TestClient) -> None:
    await signup(client)
    response = client.post(
        "/api/v1/auth/invitations/test-invitation-token/accept",
        headers=csrf_headers(client),
        json={
            "password": "another strong passphrase",
            "terms_version": "2026-08-28",
            "privacy_version": "2026-08-28",
        },
    )
    assert response.status_code == 410


async def test_invalid_credentials_use_generic_error(client: TestClient) -> None:
    await signup(client)
    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={"email": "student@example.edu", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password"


async def test_state_change_requires_csrf_and_origin(client: TestClient) -> None:
    await signup(client)
    assert client.post("/api/v1/auth/sign-out").status_code == 403


async def test_sign_out_revokes_current_session(client: TestClient) -> None:
    await signup(client)
    token = client.cookies[get_settings().csrf_cookie_name]
    response = client.post(
        "/api/v1/auth/sign-out",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": token},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


async def test_authenticated_csrf_can_be_refreshed_without_reauthentication(
    client: TestClient,
) -> None:
    await signup(client)
    client.cookies.delete(get_settings().csrf_cookie_name)

    refreshed = client.get("/api/v1/auth/csrf")
    assert refreshed.status_code == 204
    token = client.cookies[get_settings().csrf_cookie_name]

    response = client.post(
        "/api/v1/auth/sign-out",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": token},
    )
    assert response.status_code == 204


async def seed_institution_memberships() -> tuple[Institution, Institution, User, User]:
    async with TestSession() as db:
        first = Institution(code="campus-a", name="Campus A")
        second = Institution(code="campus-b", name="Campus B")
        admin = User(
            email="admin@campus-a.edu",
            password_hash=hash_password("a secure administrator passphrase"),
            role=UserRole.TNP_ADMIN.value,
        )
        student = User(
            email="student@campus-a.edu",
            password_hash=hash_password("a secure student passphrase"),
            role=UserRole.STUDENT.value,
        )
        db.add_all([first, second, admin, student])
        await db.flush()
        db.add(
            InstitutionMembership(
                institution_id=first.id,
                user_id=admin.id,
                role=UserRole.TNP_ADMIN.value,
                status=MembershipStatus.ACTIVE.value,
                verified_by_user_id=admin.id,
            )
        )
        await db.commit()
        await db.refresh(first)
        await db.refresh(second)
        await db.refresh(admin)
        await db.refresh(student)
        return first, second, admin, student


def sign_in(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    if response.json()["next_step"] == "mfa_setup":
        token = client.cookies[get_settings().csrf_cookie_name]
        headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": token}
        setup = client.post("/api/v1/auth/mfa/setup", headers=headers)
        assert setup.status_code == 200, setup.text
        confirmed = client.post(
            "/api/v1/auth/mfa/confirm",
            headers=headers,
            json={"code": totp_code(setup.json()["secret"])},
        )
        assert confirmed.status_code == 200, confirmed.text


@pytest.mark.asyncio
async def test_admin_can_verify_membership_inside_active_institution(
    client: TestClient,
) -> None:
    institution, _, _, student = await seed_institution_memberships()
    sign_in(client, "admin@campus-a.edu", "a secure administrator passphrase")
    csrf = client.cookies[get_settings().csrf_cookie_name]

    response = client.post(
        f"/api/v1/institutions/{institution.id}/memberships",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        json={"user_id": str(student.id), "role": UserRole.STUDENT.value},
    )

    assert response.status_code == 201, response.text
    assert response.json()["institution_id"] == str(institution.id)
    assert response.json()["status"] == MembershipStatus.ACTIVE.value
    async with TestSession() as db:
        events = list(
            (
                await db.scalars(
                    select(AuditEvent).where(AuditEvent.event_type == "membership.verified")
                )
            ).all()
        )
    assert len(events) == 1
    assert events[0].resource_id == str(response.json()["id"])


@pytest.mark.asyncio
async def test_membership_access_fails_closed_across_institutions_and_roles(
    client: TestClient,
) -> None:
    first, second, _, student = await seed_institution_memberships()
    sign_in(client, "admin@campus-a.edu", "a secure administrator passphrase")

    cross_institution = client.get(f"/api/v1/institutions/{second.id}/memberships")
    assert cross_institution.status_code == 403

    client.cookies.clear()
    sign_in(client, "student@campus-a.edu", "a secure student passphrase")
    student_access = client.get(f"/api/v1/institutions/{first.id}/memberships")
    assert student_access.status_code == 403
