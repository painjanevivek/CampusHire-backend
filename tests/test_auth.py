from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
    InstitutionDomain,
    InstitutionMembership,
    InstitutionRegistrationRequest,
    MembershipInvitation,
    MembershipStatus,
    PlatformAdminAssignment,
    RegistrationStatus,
    RosterImport,
    RosterImportRow,
    Session,
    StudentRegistrationRequest,
    TermsAcceptance,
    User,
    UserRole,
)
from app.models.communications import EmailDelivery
from app.models.profile import StudentProfile
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import permissions_for_role
from app.modules.auth.security import hash_password, hash_secret, totp_code
from app.modules.platform_admin.service import transfer_platform_admin

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(engine, expire_on_commit=False)


def test_reviewer_cannot_approve_institutional_policy_or_override() -> None:
    permissions = permissions_for_role(UserRole.TNP_REVIEWER.value)
    assert "applications.review" in permissions
    assert "intelligence.review" not in permissions
    assert "applications.override" not in permissions


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
        await add_approved_student_invitation(db, institution, "student23@pccoepune.org", token)
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


async def add_approved_student_invitation(
    db: AsyncSession, institution: Institution, email: str, token: str
) -> MembershipInvitation:
    domain = email.rpartition("@")[2]
    known_domain = await db.scalar(
        select(InstitutionDomain.id).where(
            InstitutionDomain.institution_id == institution.id,
            InstitutionDomain.domain == domain,
        )
    )
    if known_domain is None:
        db.add(
            InstitutionDomain(
                institution_id=institution.id,
                domain=domain,
                verification_status="verified",
                verified_at=datetime.now(UTC),
            )
        )
    actor = User(
        email=f"roster-{uuid4()}@example.edu",
        password_hash=hash_password("a test officer passphrase"),
        role=UserRole.TNP_ADMIN.value,
    )
    db.add(actor)
    await db.flush()
    roster = RosterImport(
        institution_id=institution.id,
        created_by_user_id=actor.id,
        filename="approved.csv",
        content_sha256=hash_secret(token),
        status="committed",
        total_rows=1,
        valid_rows=1,
        invited_rows=1,
        committed_at=datetime.now(UTC),
    )
    invitation = MembershipInvitation(
        institution_id=institution.id,
        email=email,
        role=UserRole.STUDENT.value,
        token_hash=hash_secret(token),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_by_user_id=actor.id,
    )
    db.add_all([roster, invitation])
    await db.flush()
    db.add(
        RosterImportRow(
            roster_import_id=roster.id,
            row_number=1,
            email=email,
            status="invited",
            invitation_id=invitation.id,
        )
    )
    await db.flush()
    return invitation


async def test_signup_fails_without_a_verified_college_identity(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        headers=csrf_headers(client),
        json={
            "name": "Asha",
            "surname": "Patil",
            "dob": "2004-05-16",
            "email": "student23@pccoepune.org",
            "password": "a secure campus passphrase",
            "re_enter_password": "a secure campus passphrase",
            "terms_version": "2026-08-28",
            "privacy_version": "2026-08-28",
        },
    )
    assert response.status_code == 409
    assert response.json() == {
        "status": "registration_unavailable",
        "message": "We could not match this college. Check your selection and try again.",
        "next_path": None,
    }
    async with TestSession() as db:
        registration = await db.scalar(select(StudentRegistrationRequest))
        assert registration is not None
        assert registration.password_hash is None
        assert registration.first_name is None
        assert registration.surname is None
        assert registration.date_of_birth is None


async def test_signup_with_selected_college_does_not_require_an_invitation(
    client: TestClient,
) -> None:
    async with TestSession() as db:
        institution = Institution(code="direct-campus", name="Direct Campus", is_active=True)
        db.add(institution)
        await db.flush()
        db.add(
            InstitutionDomain(
                institution_id=institution.id,
                domain="pccoepune.org",
                verification_status="verified",
                verified_at=datetime.now(UTC),
            )
        )
        await db.commit()

    payload = {
        "name": "Asha",
        "surname": "Patil",
        "dob": "2004-05-16",
        "email": "asha.patil23@pccoepune.org",
        "institution_id": str(institution.id),
        "password": "Campus88",
        "re_enter_password": "Campus88",
        "terms_version": "2026-08-28",
        "privacy_version": "2026-08-28",
    }
    short_password_payload = {
        **payload,
        "password": "Campus8",
        "re_enter_password": "Campus8",
    }
    short_password = client.post(
        "/api/v1/auth/signup",
        headers=csrf_headers(client),
        json=short_password_payload,
    )
    assert short_password.status_code == 422

    response = client.post("/api/v1/auth/signup", headers=csrf_headers(client), json=payload)

    assert response.status_code == 201, response.text
    assert response.json() == {
        "status": "registered",
        "message": "Account created. Continue to your student profile.",
        "next_path": "/onboarding",
    }
    assert client.get("/api/v1/auth/me").status_code == 200
    async with TestSession() as db:
        user = await db.scalar(select(User).where(User.email == "asha.patil23@pccoepune.org"))
        assert user is not None
        pending_request = await db.scalar(
            select(StudentRegistrationRequest).where(
                StudentRegistrationRequest.email == "asha.patil23@pccoepune.org",
                StudentRegistrationRequest.invitation_id.is_(None),
            )
        )
        assert pending_request is not None
        assert pending_request.status == RegistrationStatus.ACTIVATED.value
        assert pending_request.first_name == "Asha"
        assert pending_request.surname == "Patil"
        assert str(pending_request.date_of_birth) == "2004-05-16"
        membership = await db.scalar(
            select(InstitutionMembership).where(InstitutionMembership.user_id == user.id)
        )
        profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
        acceptances = list(
            (
                await db.scalars(select(TermsAcceptance).where(TermsAcceptance.user_id == user.id))
            ).all()
        )
        assert membership is not None
        assert membership.status == MembershipStatus.ACTIVE.value
        assert profile is not None
        assert profile.full_name == "Asha Patil"
        assert {item.document_type for item in acceptances} == {"terms", "privacy"}
        assert membership.verified_by_user_id is None
        assert await db.scalar(select(EmailDelivery.id)) is None


async def test_signup_college_catalog_shows_only_pccoe(
    client: TestClient,
) -> None:
    catalog = [
        ("pccoe-pune", "Pimpri Chinchwad College of Engineering (PCCOE), Pune."),
    ]
    async with TestSession() as db:
        db.add_all(
            [Institution(code=code, name=name, is_active=True) for code, name in catalog]
            + [Institution(code="old-demo-campus", name="Old Demo College", is_active=True)]
        )
        await db.commit()

    response = client.get("/api/v1/auth/signup/institutions")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {name for _, name in catalog}
    assert [item["name"] for item in response.json()] == [name for _, name in catalog]
    assert len(response.json()) == len(catalog)


async def test_unlinked_student_invitation_cannot_activate_an_account(
    client: TestClient,
) -> None:
    token = "unlinked-student-invitation-code"  # noqa: S105
    async with TestSession() as db:
        institution = Institution(code="unlinked-campus", name="Unlinked Campus")
        db.add(institution)
        await db.flush()
        db.add_all(
            [
                InstitutionDomain(
                    institution_id=institution.id,
                    domain="unlinked.edu",
                    verification_status="verified",
                    verified_at=datetime.now(UTC),
                ),
                MembershipInvitation(
                    institution_id=institution.id,
                    email="student@unlinked.edu",
                    role=UserRole.STUDENT.value,
                    token_hash=hash_secret(token),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                ),
            ]
        )
        await db.commit()
    assert client.get(f"/api/v1/auth/invitations/{token}").status_code == 410
    activated = client.post(
        f"/api/v1/auth/invitations/{token}/accept",
        headers=csrf_headers(client),
        json={
            "password": "a synthetic student passphrase",
            "terms_version": "2026-08-28",
            "privacy_version": "2026-08-28",
        },
    )
    assert activated.status_code == 410
    assert client.get("/api/v1/auth/me").status_code == 401


async def test_institution_registration_flags_similar_existing_name_without_granting_access(
    client: TestClient,
) -> None:
    async with TestSession() as db:
        db.add(Institution(code="existing-campus", name="Example Institute of Technology"))
        await db.commit()

    response = client.post(
        "/api/v1/auth/institution-registrations",
        headers=csrf_headers(client),
        json={
            "institution_name": "Example Institute Of Technology",
            "institution_code": "example-new",
            "institutional_email": "admin@example-new.edu",
            "domain": "example-new.edu",
        },
    )
    assert response.status_code == 202, response.text
    async with TestSession() as db:
        request = await db.scalar(select(InstitutionRegistrationRequest))
        assert request is not None
        assert request.duplicate_detected is True
        assert await db.scalar(select(User.id).where(User.email == "admin@example-new.edu")) is None


async def test_invitation_acceptance_normalizes_email_and_creates_student_session(
    client: TestClient,
) -> None:
    payload = await signup(client)
    assert payload["email"] == "student23@pccoepune.org"
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
        json={"email": "student23@pccoepune.org", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid username, email, or password"


async def test_demo_login_is_hidden_when_disabled(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/demo-sign-in",
        headers=csrf_headers(client),
        json={"role": "student"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "demo_login_unavailable"


async def test_demo_login_uses_server_credentials_when_mfa_is_not_enrolled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, demo_tnp, _ = await seed_institution_memberships()
    async with TestSession() as db:
        demo_admin = User(
            email="platform-demo@example.com",
            username="platform-demo",
            password_hash=hash_password("a secure platform demo passphrase"),
            role=UserRole.PLATFORM_ADMIN.value,
        )
        db.add(demo_admin)
        await db.flush()
        await transfer_platform_admin(
            db,
            user_id=demo_admin.id,
            reason="Explicit synthetic test administrator migration",
            actor_user_id=None,
        )
    with monkeypatch.context() as patch:
        patch.setenv("DEMO_LOGIN_ENABLED", "true")
        patch.setenv("DEMO_ADMIN_MFA_BYPASS", "true")
        patch.setenv("DEMO_STUDENT_EMAIL", "student@campus-a.edu")
        patch.setenv("DEMO_STUDENT_PASSWORD", "a secure student passphrase")
        patch.setenv("DEMO_TNP_EMAIL", "admin@campus-a.edu")
        patch.setenv("DEMO_TNP_USERNAME", "admin")
        patch.setenv("DEMO_TNP_PASSWORD", "a secure administrator passphrase")
        patch.setenv("DEMO_ADMIN_EMAIL", "platform-demo@example.com")
        patch.setenv("DEMO_ADMIN_PASSWORD", "a secure platform demo passphrase")
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
        tnp = client.post(
            "/api/v1/auth/demo-sign-in",
            headers=csrf_headers(client),
            json={"role": "tnp_admin"},
        )
        assert tnp.status_code == 200, tnp.text
        assert tnp.json()["user"]["role"] == "tnp_admin"
        assert tnp.json()["user"]["workspace"] == "tnp"
        assert tnp.json()["next_step"] == "complete"
        assert client.get("/api/v1/auth/me").status_code == 200
        async with TestSession() as db:
            session = await db.scalar(select(Session).where(Session.user_id == demo_tnp.id))
            assert session is not None
            assert session.mfa_verified_at is not None

        client.cookies.clear()
        admin = client.post(
            "/api/v1/auth/demo-sign-in",
            headers=csrf_headers(client),
            json={"role": "platform_admin"},
        )
        assert admin.status_code == 200, admin.text
        assert admin.json()["user"]["role"] == "platform_admin"
        assert admin.json()["user"]["workspace"] == "admin"

        patch.setenv("DEMO_ADMIN_MFA_BYPASS", "false")
        get_settings.cache_clear()
        client.cookies.clear()
        protected_admin = client.post(
            "/api/v1/auth/demo-sign-in",
            headers=csrf_headers(client),
            json={"role": "platform_admin"},
        )
        assert protected_admin.status_code == 200, protected_admin.text
        assert protected_admin.json()["next_step"] == "complete"
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


async def test_demo_admin_mfa_bypass_requires_demo_login() -> None:
    with pytest.raises(ValueError, match="requires DEMO_LOGIN_ENABLED"):
        Settings(app_env="development", demo_admin_mfa_bypass=True)


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
        json={
            "user_id": str(student.id),
            "role": UserRole.STUDENT.value,
            "reason": "Verified against the institution enrollment record.",
        },
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
async def test_only_owner_can_manage_administrator_memberships(
    client: TestClient,
) -> None:
    institution, _, admin, student = await seed_institution_memberships()
    async with TestSession() as db:
        owner = User(
            email="owner@campus-a.edu",
            password_hash=hash_password("a secure owner passphrase"),
            role=UserRole.TNP_OWNER.value,
        )
        db.add(owner)
        await db.flush()
        owner_membership = InstitutionMembership(
            institution_id=institution.id,
            user_id=owner.id,
            role=UserRole.TNP_OWNER.value,
            status=MembershipStatus.ACTIVE.value,
            verified_by_user_id=owner.id,
        )
        db.add(owner_membership)
        await db.commit()
        await db.refresh(owner_membership)

    sign_in(client, admin.email, "a secure administrator passphrase")
    headers = {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": client.cookies[get_settings().csrf_cookie_name],
    }
    assigned = client.post(
        f"/api/v1/institutions/{institution.id}/memberships",
        headers=headers,
        json={
            "user_id": str(student.id),
            "role": UserRole.TNP_REVIEWER.value,
            "reason": "Assign reviewer access for the current placement cycle.",
        },
    )
    assert assigned.status_code == 403
    assert assigned.json()["error"]["code"] == "membership_permission_denied"

    suspended = client.patch(
        f"/api/v1/institutions/{institution.id}/memberships/{owner_membership.id}",
        headers=headers,
        json={
            "status": MembershipStatus.SUSPENDED.value,
            "reason": "Attempted change outside the administrator authority boundary.",
        },
    )
    assert suspended.status_code == 403
    assert suspended.json()["error"]["code"] == "membership_permission_denied"

    client.cookies.clear()
    sign_in(client, owner.email, "a secure owner passphrase")
    owner_headers = {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": client.cookies[get_settings().csrf_cookie_name],
    }
    self_change = client.patch(
        f"/api/v1/institutions/{institution.id}/memberships/{owner_membership.id}",
        headers=owner_headers,
        json={
            "status": MembershipStatus.REVOKED.value,
            "reason": "Attempt to remove the currently authenticated institution owner.",
        },
    )
    assert self_change.status_code == 403
    assert self_change.json()["error"]["code"] == "membership_permission_denied"


@pytest.mark.asyncio
async def test_membership_directory_is_server_paginated_and_tenant_filtered(
    client: TestClient,
) -> None:
    institution, other_institution, _, _ = await seed_institution_memberships()
    async with TestSession() as db:
        users = [
            User(
                email=f"student-{index:02d}@campus-a.edu",
                password_hash=hash_password("a secure student passphrase"),
                role=UserRole.STUDENT.value,
            )
            for index in range(23)
        ]
        outsider = User(
            email="student-outsider@campus-b.edu",
            password_hash=hash_password("a secure student passphrase"),
            role=UserRole.STUDENT.value,
        )
        db.add_all([*users, outsider])
        await db.flush()
        db.add_all(
            [
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=user.id,
                    role=UserRole.STUDENT.value,
                    status=MembershipStatus.ACTIVE.value,
                )
                for user in users
            ]
            + [
                InstitutionMembership(
                    institution_id=other_institution.id,
                    user_id=outsider.id,
                    role=UserRole.STUDENT.value,
                    status=MembershipStatus.ACTIVE.value,
                )
            ]
        )
        await db.commit()

    sign_in(client, "admin@campus-a.edu", "a secure administrator passphrase")
    first_page = client.get(
        f"/api/v1/institutions/{institution.id}/memberships"
        "?role=student&page=1&page_size=10&sort=email"
    )
    assert first_page.status_code == 200, first_page.text
    assert first_page.json()["total"] == 23
    assert len(first_page.json()["items"]) == 10
    assert all(item["email"].endswith("@campus-a.edu") for item in first_page.json()["items"])

    filtered = client.get(
        f"/api/v1/institutions/{institution.id}/memberships"
        "?role=student&query=student-22&page=1&page_size=10"
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["email"] == "student-22@campus-a.edu"


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


@pytest.mark.asyncio
async def test_reviewer_cannot_apply_bulk_or_override_decisions(client: TestClient) -> None:
    institution, _, _, _ = await seed_institution_memberships()
    async with TestSession() as db:
        reviewer = User(
            institution_id=institution.id,
            email="reviewer@campus-a.edu",
            password_hash=hash_password("a secure reviewer passphrase"),
            role=UserRole.TNP_REVIEWER.value,
        )
        db.add(reviewer)
        await db.flush()
        db.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=reviewer.id,
                role=UserRole.TNP_REVIEWER.value,
                status=MembershipStatus.ACTIVE.value,
                verified_by_user_id=reviewer.id,
            )
        )
        await db.commit()

    sign_in(client, reviewer.email, "a secure reviewer passphrase")
    headers = {
        "Origin": "http://localhost:3000",
        "X-CSRF-Token": client.cookies[get_settings().csrf_cookie_name],
    }
    override = client.post(
        f"/api/v1/admin/recruitment/applications/{uuid4()}/override",
        headers=headers,
        json={
            "status": "shortlisted",
            "reason": "A reviewer must not be able to authorize policy exceptions.",
            "policy_reference": "Placement Policy section 4.2",
        },
    )
    assert override.status_code == 403
    assert override.json()["error"]["code"] == "permission_denied"

    bulk = client.post(
        "/api/v1/admin/recruitment/applications/bulk/status",
        headers=headers,
        json={
            "application_ids": [str(uuid4())],
            "status": "shortlisted",
            "reason": "A reviewer must not be able to apply a mass decision.",
            "confirmation": "APPLY BULK STATUS",
        },
    )
    assert bulk.status_code == 403
    assert bulk.json()["error"]["code"] == "permission_denied"

    policy = client.post(
        "/api/v1/admin/intelligence/policies",
        headers=headers,
        json={
            "title": "Reviewer-created policy",
            "source_reference": "Unapproved reviewer source",
            "sections": [{"section": "1", "page": 1, "text": "Must not be accepted"}],
        },
    )
    assert policy.status_code == 403
    assert policy.json()["error"]["code"] == "permission_denied"


async def seed_institution_owner() -> tuple[Institution, User]:
    async with TestSession() as db:
        institution = Institution(code="owner-campus", name="Owner Campus")
        owner = User(
            institution_id=institution.id,
            email="owner@owner-campus.edu",
            username="owner.admin",
            password_hash=hash_password("a secure owner passphrase"),
            role=UserRole.TNP_OWNER.value,
        )
        db.add_all([institution, owner])
        await db.flush()
        db.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=owner.id,
                role=UserRole.TNP_OWNER.value,
                status=MembershipStatus.ACTIVE.value,
                verified_at=datetime.now(UTC),
                verified_by_user_id=owner.id,
            )
        )
        await db.commit()
        return institution, owner


async def seed_platform_admin() -> User:
    async with TestSession() as db:
        admin = User(
            email="platform-admin@example.com",
            username="platform-admin",
            password_hash=hash_password("a secure platform passphrase"),
            role=UserRole.PLATFORM_ADMIN.value,
        )
        db.add(admin)
        await db.flush()
        db.add(PlatformAdminAssignment(singleton_key=1, user_id=admin.id))
        await db.commit()
        return admin


async def test_legacy_owner_uses_tnp_workspace_not_platform_admin_workspace(
    client: TestClient,
) -> None:
    _, owner = await seed_institution_owner()

    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": owner.username,
            "password": "a secure owner passphrase",
            "workspace": "admin",
        },
    )

    assert response.status_code == 401

    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": owner.username,
            "password": "a secure owner passphrase",
            "workspace": "tnp",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["user"]["workspace"] == "tnp"


async def test_singleton_platform_admin_receives_only_platform_capabilities(
    client: TestClient,
) -> None:
    await seed_platform_admin()

    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": "platform-admin",
            "password": "a secure platform passphrase",
            "workspace": "admin",
        },
    )

    assert response.status_code == 200, response.text
    user = response.json()["user"]
    assert user["workspace"] == "admin"
    assert "platform.institutions.manage" in user["capabilities"]
    assert "applications.review" not in user["capabilities"]
    assert client.get("/api/v1/platform/dashboard").status_code == 200
    assert client.get("/api/v1/admin/recruitment/applications").status_code == 403


async def test_platform_admin_provisions_institution_with_attributed_audit(
    client: TestClient,
) -> None:
    admin = await seed_platform_admin()
    sign_in(client, "platform-admin", "a secure platform passphrase")

    response = client.post(
        "/api/v1/platform/institutions",
        headers=csrf_headers(client),
        json={
            "institution_code": "new-campus",
            "institution_name": "New Campus",
            "admin_email": "placement@new-campus.edu",
        },
    )

    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["admin_invitation_token"]
    async with TestSession() as db:
        invitation = await db.get(
            MembershipInvitation, UUID(response.json()["admin_invitation_id"])
        )
        audit = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "institution.provisioned",
                AuditEvent.actor_user_id == admin.id,
            )
        )
        assert invitation is not None and invitation.role == UserRole.TNP_OWNER.value
        assert audit is not None


async def test_platform_assignment_and_tnp_context_switch_are_tenant_scoped(
    client: TestClient,
) -> None:
    first, officer = await seed_institution_owner()
    async with TestSession() as db:
        second = Institution(code="second-campus", name="Second Campus")
        unassigned = Institution(code="unassigned-campus", name="Unassigned Campus")
        db.add_all([second, unassigned])
        await db.commit()
        second_id = second.id
        unassigned_id = unassigned.id
    await seed_platform_admin()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    assigned = client.post(
        f"/api/v1/platform/institutions/{second_id}/staff-assignments",
        headers=csrf_headers(client),
        json={
            "username": officer.username,
            "role": "tnp_admin",
            "reason": "Officer is covering the second institution.",
        },
    )
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["institution_id"] == str(second_id)
    changed = client.patch(
        f"/api/v1/platform/institutions/{second_id}/staff-accounts/{assigned.json()['id']}",
        headers=csrf_headers(client),
        json={
            "status": "active",
            "role": "tnp_reviewer",
            "reason": "Second campus only needs assigned reviews.",
        },
    )
    assert changed.status_code == 200, changed.text
    async with TestSession() as db:
        stored = await db.get(User, officer.id)
        assert stored is not None and stored.role == officer.role

    client.cookies.clear()
    signed_in = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": officer.username,
            "password": "a secure owner passphrase",
            "workspace": "tnp",
        },
    )
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["institution_id"] in {str(first.id), str(second_id)}
    memberships = client.get("/api/v1/auth/memberships")
    assert memberships.status_code == 200, memberships.text
    assert {item["institution_id"] for item in memberships.json()} == {
        str(first.id), str(second_id)
    }
    first_choice = next(
        item for item in memberships.json() if item["institution_id"] == str(first.id)
    )

    switched = client.post(
        "/api/v1/auth/active-membership",
        headers=csrf_headers(client),
        json={"membership_id": assigned.json()["id"]},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["institution_id"] == str(second_id)
    assert switched.json()["role"] == "tnp_reviewer"
    assert client.get("/api/v1/auth/me").json()["institution_id"] == str(second_id)
    assert client.get(f"/api/v1/institutions/{first.id}/memberships").status_code == 403
    assert client.get(f"/api/v1/institutions/{second_id}/memberships").status_code == 403
    restored = client.post(
        "/api/v1/auth/active-membership",
        headers=csrf_headers(client),
        json={"membership_id": first_choice["id"]},
    )
    assert restored.status_code == 200
    assert restored.json()["role"] == "tnp_owner"
    assert client.get(f"/api/v1/institutions/{first.id}/memberships").status_code == 200

    denied = client.post(
        "/api/v1/auth/active-membership",
        headers=csrf_headers(client),
        json={"membership_id": str(uuid4())},
    )
    assert denied.status_code == 404
    assert client.get(f"/api/v1/institutions/{unassigned_id}/memberships").status_code == 403


async def test_manual_student_recovery_is_scoped_audited_and_single_use(
    client: TestClient,
) -> None:
    institution, officer = await seed_institution_owner()
    async with TestSession() as db:
        student = User(
            email="recovery@student-campus.edu",
            password_hash=hash_password("original student passphrase"),
            role=UserRole.STUDENT.value,
            institution_id=institution.id,
        )
        db.add(student)
        await db.flush()
        db.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=student.id,
                role=UserRole.STUDENT.value,
                status=MembershipStatus.ACTIVE.value,
            )
        )
        await db.commit()
        student_id = student.id
    sign_in(client, officer.username, "a secure owner passphrase")
    issued = client.post(
        f"/api/v1/institutions/{institution.id}/students/{student_id}/manual-recovery",
        headers=csrf_headers(client),
        json={
            "identity_check_method": "in-person student ID check",
            "identity_check_reference": "synthetic-helpdesk-123",
            "reason": "Student lost access to the original passphrase.",
        },
    )
    assert issued.status_code == 200, issued.text
    assert issued.headers["cache-control"] == "no-store"
    code = issued.json()["reset_code"]
    assert len(code) >= 20
    async with TestSession() as db:
        audit = await db.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "auth.manual_recovery_issued")
        )
        assert audit is not None and audit.actor_user_id == officer.id
    wrong_tenant = client.post(
        f"/api/v1/institutions/{uuid4()}/students/{student_id}/manual-recovery",
        headers=csrf_headers(client),
        json={
            "identity_check_method": "in-person student ID check",
            "identity_check_reference": "synthetic-helpdesk-123",
            "reason": "Student lost access to the original passphrase.",
        },
    )
    assert wrong_tenant.status_code == 403
    client.cookies.clear()
    confirmed = client.post(
        f"/api/v1/auth/password-reset/{code}/confirm",
        headers=csrf_headers(client),
        json={"password": "replacement student passphrase"},
    )
    replay = client.post(
        f"/api/v1/auth/password-reset/{code}/confirm",
        headers=csrf_headers(client),
        json={"password": "another student passphrase"},
    )
    assert confirmed.status_code == 204
    assert replay.status_code == 410


async def test_only_platform_admin_can_issue_staff_manual_recovery(client: TestClient) -> None:
    _, officer = await seed_institution_owner()
    await seed_platform_admin()
    payload = {
        "identity_check_method": "verified helpdesk callback",
        "identity_check_reference": "synthetic-helpdesk-456",
        "reason": "Officer lost access to the account.",
    }
    sign_in(client, officer.username, "a secure owner passphrase")
    denied = client.post(
        f"/api/v1/platform/staff-accounts/{officer.id}/manual-recovery",
        headers=csrf_headers(client),
        json=payload,
    )
    assert denied.status_code == 403

    client.cookies.clear()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    issued = client.post(
        f"/api/v1/platform/staff-accounts/{officer.id}/manual-recovery",
        headers=csrf_headers(client),
        json=payload,
    )
    assert issued.status_code == 200, issued.text
    assert issued.headers["cache-control"] == "no-store"
    assert len(issued.json()["reset_code"]) >= 20
    cannot_reset_admin = client.post(
        f"/api/v1/platform/staff-accounts/{client.get('/api/v1/auth/me').json()['id']}/manual-recovery",
        headers=csrf_headers(client),
        json=payload,
    )
    assert cannot_reset_admin.status_code == 404


@pytest.mark.asyncio
async def test_platform_admin_provisions_staff_credentials_with_first_sign_in_gates(
    client: TestClient,
) -> None:
    institution, _ = await seed_institution_owner()
    await seed_platform_admin()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    csrf = client.cookies[get_settings().csrf_cookie_name]

    created = client.post(
        f"/api/v1/platform/institutions/{institution.id}/staff-accounts",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        json={
            "username": "placement.reviewer",
            "password": "a secure officer passphrase",
            "role": "tnp_reviewer",
            "reason": "Assigned to review placement applications.",
        },
    )

    assert created.status_code == 201, created.text
    assert created.json()["role"] == "tnp_reviewer"
    assert created.json()["username"] == "placement.reviewer"
    assert created.json()["requires_terms_acceptance"] is True
    assert "password" not in created.json()

    client.cookies.clear()
    wrong_workspace = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": "placement.reviewer",
            "password": "a secure officer passphrase",
            "workspace": "admin",
        },
    )
    assert wrong_workspace.status_code == 401

    client.cookies.clear()
    staff_sign_in = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": "placement.reviewer",
            "password": "a secure officer passphrase",
            "workspace": "tnp",
        },
    )
    assert staff_sign_in.status_code == 200, staff_sign_in.text
    assert staff_sign_in.json()["next_step"] == "terms_acceptance"
    assert client.get("/api/v1/auth/me").status_code == 403

    accepted = client.post(
        "/api/v1/auth/terms/accept",
        headers=csrf_headers(client),
        json={"terms_version": "2026-08-28", "privacy_version": "2026-08-28"},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["next_step"] == "complete"

    headers = csrf_headers(client)
    setup = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(setup.json()["secret"])},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert client.get("/api/v1/auth/me").json()["role"] == "tnp_reviewer"

    async with TestSession() as db:
        user = await db.scalar(select(User).where(User.username == "placement.reviewer"))
        assert user is not None
        assert user.requires_terms_acceptance is False
        assert user.password_hash.startswith("$argon2id$")
        acceptances = list(
            (
                await db.scalars(select(TermsAcceptance).where(TermsAcceptance.user_id == user.id))
            ).all()
        )
        assert {item.document_type for item in acceptances} == {"terms", "privacy"}
        assert await db.scalar(
            select(AuditEvent.id).where(AuditEvent.event_type == "staff_account.created")
        )
        assert await db.scalar(
            select(AuditEvent.id).where(AuditEvent.event_type == "auth.staff_terms_accepted")
        )


@pytest.mark.asyncio
async def test_non_owner_cannot_provision_tnp_accounts(client: TestClient) -> None:
    institution, _, _, _ = await seed_institution_memberships()
    sign_in(client, "admin@campus-a.edu", "a secure administrator passphrase")

    response = client.post(
        f"/api/v1/institutions/{institution.id}/staff-accounts",
        headers=csrf_headers(client),
        json={
            "username": "blocked.auditor",
            "password": "a secure blocked passphrase",
            "role": "tnp_auditor",
            "reason": "Attempted administrator-only account provisioning.",
        },
    )

    assert response.status_code == 403
    async with TestSession() as db:
        assert await db.scalar(select(User.id).where(User.username == "blocked.auditor")) is None


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
        json={
            "user_id": str(student.id),
            "role": UserRole.STUDENT.value,
            "reason": "Verified against the institution enrollment record.",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "reauthentication_required"
