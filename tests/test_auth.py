from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import rate_limit
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.main import app
from app.models import Base
from app.models.auth import (
    AuditEvent,
    Institution,
    InstitutionMembership,
    MembershipInvitation,
    MembershipStatus,
    Session,
    User,
    UserRole,
)
from app.modules.audit.service import record_audit_event
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


async def test_demo_login_is_hidden_when_disabled(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/demo-sign-in",
        headers=csrf_headers(client),
        json={"role": "student"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "demo_login_unavailable"


async def test_demo_login_uses_server_credentials_and_preserves_admin_mfa(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_institution_memberships()
    with monkeypatch.context() as patch:
        patch.setenv("DEMO_LOGIN_ENABLED", "true")
        patch.setenv("DEMO_STUDENT_EMAIL", "student@campus-a.edu")
        patch.setenv("DEMO_STUDENT_PASSWORD", "a secure student passphrase")
        patch.setenv("DEMO_ADMIN_EMAIL", "admin@campus-a.edu")
        patch.setenv("DEMO_ADMIN_PASSWORD", "a secure administrator passphrase")
        get_settings.cache_clear()

        student = client.post(
            "/api/v1/auth/demo-sign-in",
            headers=csrf_headers(client),
            json={"role": "student"},
        )
        assert student.status_code == 200, student.text
        assert student.json()["user"]["role"] == "student"
        assert student.json()["next_step"] == "complete"

        client.cookies.clear()
        admin = client.post(
            "/api/v1/auth/demo-sign-in",
            headers=csrf_headers(client),
            json={"role": "tnp_admin"},
        )
        assert admin.status_code == 200, admin.text
        assert admin.json()["user"]["role"] == "tnp_admin"
        assert admin.json()["next_step"] == "mfa_setup"
    get_settings.cache_clear()


async def test_demo_login_configuration_is_rejected_outside_development() -> None:
    with pytest.raises(ValueError, match="Demo login is restricted"):
        Settings(
            app_env="staging",
            demo_login_enabled=True,
            demo_student_email="student+demo@example.com",
            demo_student_password="a synthetic student passphrase",  # noqa: S106
            demo_admin_email="admin+demo@example.com",
            demo_admin_password="a synthetic administrator passphrase",  # noqa: S106
        )


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


@pytest.mark.asyncio
async def test_auditor_has_tenant_scoped_read_only_audit_access_and_safe_export(
    client: TestClient,
) -> None:
    first, second, _, _ = await seed_institution_memberships()
    async with TestSession() as db:
        auditor = User(
            institution_id=first.id,
            email="auditor@campus-a.edu",
            password_hash=hash_password("a secure auditor passphrase"),
            role=UserRole.TNP_AUDITOR.value,
        )
        db.add(auditor)
        await db.flush()
        db.add(
            InstitutionMembership(
                institution_id=first.id,
                user_id=auditor.id,
                role=UserRole.TNP_AUDITOR.value,
                status=MembershipStatus.ACTIVE.value,
                verified_by_user_id=auditor.id,
            )
        )
        record_audit_event(
            db,
            actor_user_id=auditor.id,
            institution_id=first.id,
            event_type="governance.test",
            resource_type="policy",
            resource_id="policy-1",
            reason="=2+2",
            correlation_id="correlation-a",
            details={"safe_count": 2, "resume_content": "must not persist"},
        )
        record_audit_event(
            db,
            institution_id=second.id,
            event_type="governance.test",
            resource_type="policy",
            resource_id="policy-other-tenant",
        )
        await db.commit()

    sign_in(client, "auditor@campus-a.edu", "a secure auditor passphrase")
    response = client.get("/api/v1/admin/audit/events?action=governance.test")
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["details"] == {"safe_count": 2}

    export = client.get("/api/v1/admin/audit/export.csv?action=governance.test")
    assert export.status_code == 200
    assert "'=2+2" in export.text
    assert "policy-other-tenant" not in export.text

    csrf = client.cookies[get_settings().csrf_cookie_name]
    mutation = client.post(
        "/api/v1/admin/recruitment/companies",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        json={"name": "Forbidden Company"},
    )
    assert mutation.status_code == 403
    assert mutation.json()["error"]["code"] == "permission_denied"


async def test_audit_export_does_not_silently_truncate_after_one_hundred_rows(
    client: TestClient,
) -> None:
    institution, _, _, _ = await seed_institution_memberships()
    async with TestSession() as db:
        auditor = User(
            institution_id=institution.id,
            email="bulk-auditor@campus-a.edu",
            password_hash=hash_password("a secure auditor passphrase"),
            role=UserRole.TNP_AUDITOR.value,
        )
        db.add(auditor)
        await db.flush()
        db.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=auditor.id,
                role=UserRole.TNP_AUDITOR.value,
                status=MembershipStatus.ACTIVE.value,
            )
        )
        db.add_all(
            [
                AuditEvent(
                    actor_user_id=auditor.id,
                    institution_id=institution.id,
                    event_type="governance.bulk_test",
                    resource_type="test",
                    resource_id=str(index),
                )
                for index in range(125)
            ]
        )
        await db.commit()
    sign_in(client, auditor.email, "a secure auditor passphrase")
    export = client.get("/api/v1/admin/audit/export.csv?action=governance.bulk_test")
    assert export.status_code == 200
    assert len(export.text.strip().splitlines()) == 126


@pytest.mark.asyncio
async def test_sensitive_membership_changes_require_recent_mfa(client: TestClient) -> None:
    institution, _, admin, student = await seed_institution_memberships()
    sign_in(client, "admin@campus-a.edu", "a secure administrator passphrase")
    async with TestSession() as db:
        session = await db.scalar(
            select(Session).where(Session.user_id == admin.id, Session.revoked_at.is_(None))
        )
        assert session is not None
        session.mfa_verified_at = datetime.now(UTC) - timedelta(minutes=11)
        await db.commit()

    csrf = client.cookies[get_settings().csrf_cookie_name]
    response = client.post(
        f"/api/v1/institutions/{institution.id}/memberships",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        json={"user_id": str(student.id), "role": UserRole.STUDENT.value},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "reauthentication_required"
