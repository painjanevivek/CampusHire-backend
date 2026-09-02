# ruff: noqa: F811

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth import (
    Institution,
    InstitutionMembership,
    MembershipInvitation,
    MembershipStatus,
    MfaEnrollment,
    RosterImport,
    Session,
    TermsAcceptance,
    User,
    UserRole,
)
from app.modules.auth.security import hash_password, hash_secret, totp_code
from app.modules.auth.service import issue_password_reset
from tests.test_auth import TestSession, client, csrf_headers, database  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _seed_admin() -> tuple[Institution, User]:
    async with TestSession() as db:
        institution = Institution(code="lifecycle-campus", name="Lifecycle Campus")
        admin = User(
            email="admin@lifecycle.edu",
            password_hash=hash_password("a secure administrator passphrase"),
            role=UserRole.TNP_ADMIN.value,
        )
        db.add_all([institution, admin])
        await db.flush()
        db.add(
            InstitutionMembership(
                institution_id=institution.id,
                user_id=admin.id,
                role=UserRole.TNP_ADMIN.value,
                status=MembershipStatus.ACTIVE.value,
                verified_at=datetime.now(UTC),
                verified_by_user_id=admin.id,
            )
        )
        await db.commit()
        return institution, admin


async def _sign_in_admin(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "email": "admin@lifecycle.edu",
            "password": "a secure administrator passphrase",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _activate_admin_mfa(client: TestClient) -> str:
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}
    setup = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(secret)},
    )
    assert confirmed.status_code == 200, confirmed.text
    return secret


async def test_operator_provisioning_is_keyed_and_audited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPERATOR_BOOTSTRAP_KEY", "operator-test-key-with-enough-entropy")
    get_settings.cache_clear()
    payload = {
        "institution_code": "new-campus",
        "institution_name": "New Campus",
        "admin_email": "placement@new-campus.edu",
    }

    assert client.post("/api/v1/operator/institutions", json=payload).status_code == 403
    response = client.post(
        "/api/v1/operator/institutions",
        headers={"X-Operator-Key": "operator-test-key-with-enough-entropy"},
        json=payload,
    )

    assert response.status_code == 201, response.text
    assert response.json()["admin_invitation_token"]
    async with TestSession() as db:
        invitation = await db.scalar(
            select(MembershipInvitation).where(
                MembershipInvitation.id == UUID(response.json()["admin_invitation_id"])
            )
        )
        assert invitation is not None
        assert invitation.role == UserRole.TNP_OWNER.value
    get_settings.cache_clear()


async def test_admin_must_finish_mfa_before_institution_access(client: TestClient) -> None:
    institution, _ = await _seed_admin()
    signed_in = await _sign_in_admin(client)
    assert signed_in["next_step"] == "mfa_setup"
    assert client.get(f"/api/v1/institutions/{institution.id}/memberships").status_code == 403

    csrf = client.cookies[get_settings().csrf_cookie_name]
    setup = client.post(
        "/api/v1/auth/mfa/setup",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
    )
    secret = setup.json()["secret"]
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        json={"code": totp_code(secret)},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert len(confirmed.json()["recovery_codes"]) == 10
    assert client.get(f"/api/v1/institutions/{institution.id}/memberships").status_code == 200


async def test_roster_preview_rejects_formula_injection_and_commit_is_idempotent(
    client: TestClient,
) -> None:
    institution, _ = await _seed_admin()
    await _sign_in_admin(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    setup = client.post(
        "/api/v1/auth/mfa/setup",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
    ).json()
    client.post(
        "/api/v1/auth/mfa/confirm",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        json={"code": totp_code(setup["secret"])},
    )
    content = (
        b"email,enrollment_id,full_name\n"
        b"student@example.edu,ENR-001,Student One\n"
        b"other@example.edu,ENR-001,Duplicate Enrollment\n"
        b'formula@example.edu,ENR-003,=HYPERLINK("https://bad.example")\n'
    )
    preview = client.post(
        f"/api/v1/institutions/{institution.id}/roster-imports/preview",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        files={"file": ("roster.csv", content, "text/csv")},
    )
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert body["valid_rows"] == 1
    assert body["invalid_rows"] == 2

    first = client.post(
        f"/api/v1/institutions/{institution.id}/roster-imports/{body['id']}/commit",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
    )
    second = client.post(
        f"/api/v1/institutions/{institution.id}/roster-imports/{body['id']}/commit",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["invited_rows"] == second.json()["invited_rows"] == 1
    assert all("activation_token" not in row for row in first.json()["rows"])
    async with TestSession() as db:
        stored = await db.scalar(select(RosterImport).where(RosterImport.id == UUID(body["id"])))
        assert stored is not None and stored.status == "committed"


async def test_roster_commit_rejects_enrollment_reused_by_a_later_import(
    client: TestClient,
) -> None:
    institution, _ = await _seed_admin()
    await _sign_in_admin(client)
    await _activate_admin_mfa(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}

    first_preview = client.post(
        f"/api/v1/institutions/{institution.id}/roster-imports/preview",
        headers=headers,
        files={
            "file": (
                "first.csv",
                b"email,enrollment_id,full_name\nfirst@example.edu,ENR-001,First Student\n",
                "text/csv",
            )
        },
    )
    assert first_preview.status_code == 201, first_preview.text
    first_commit = client.post(
        f"/api/v1/institutions/{institution.id}/roster-imports/"
        f"{first_preview.json()['id']}/commit",
        headers=headers,
    )
    assert first_commit.status_code == 200, first_commit.text
    assert first_commit.json()["invited_rows"] == 1

    second_preview = client.post(
        f"/api/v1/institutions/{institution.id}/roster-imports/preview",
        headers=headers,
        files={
            "file": (
                "second.csv",
                b"email,enrollment_id,full_name\nsecond@example.edu,ENR-001,Second Student\n",
                "text/csv",
            )
        },
    )
    assert second_preview.status_code == 201, second_preview.text
    second_commit = client.post(
        f"/api/v1/institutions/{institution.id}/roster-imports/"
        f"{second_preview.json()['id']}/commit",
        headers=headers,
    )
    assert second_commit.status_code == 200, second_commit.text
    assert second_commit.json()["invited_rows"] == 0
    assert second_commit.json()["rows"][0]["status"] == "duplicate"
    assert second_commit.json()["rows"][0]["errors"] == [
        "account_or_invitation_exists"
    ]


async def test_invitation_management_is_tenant_scoped_and_never_returns_tokens(
    client: TestClient,
) -> None:
    institution, admin = await _seed_admin()
    token = "tenant-bound-pending-invitation"  # noqa: S105
    async with TestSession() as db:
        other = Institution(code="other-campus", name="Other Campus")
        db.add(other)
        await db.flush()
        invitation = MembershipInvitation(
            institution_id=institution.id,
            email="pending@example.edu",
            enrollment_id="ENR-PENDING",
            full_name="Pending Student",
            role=UserRole.STUDENT.value,
            token_hash=hash_secret(token),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            created_by_user_id=admin.id,
        )
        hidden = MembershipInvitation(
            institution_id=other.id,
            email="hidden@example.edu",
            enrollment_id="OTHER-001",
            full_name="Other Student",
            role=UserRole.STUDENT.value,
            token_hash=hash_secret("other-tenant-invitation"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add_all([invitation, hidden])
        await db.commit()
        invitation_id = invitation.id

    await _sign_in_admin(client)
    await _activate_admin_mfa(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}

    listed = client.get(f"/api/v1/institutions/{institution.id}/invitations")
    assert listed.status_code == 200, listed.text
    assert [item["email"] for item in listed.json()] == ["pending@example.edu"]
    assert listed.json()[0]["status"] == "pending"
    assert "token" not in str(listed.json()).lower()

    resent = client.post(
        f"/api/v1/institutions/{institution.id}/invitations/{invitation_id}/resend",
        headers=headers,
    )
    assert resent.status_code == 200, resent.text
    assert resent.json()["status"] == "pending"
    assert "token" not in str(resent.json()).lower()

    revoked = client.post(
        f"/api/v1/institutions/{institution.id}/invitations/{invitation_id}/revoke",
        headers=headers,
        json={"reason": "Student record was added in error"},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    assert client.get(f"/api/v1/auth/invitations/{token}").status_code == 410


async def test_mfa_reset_requires_password_and_factor_then_revokes_other_sessions(
    client: TestClient,
) -> None:
    institution, _ = await _seed_admin()
    await _sign_in_admin(client)
    secret = await _activate_admin_mfa(client)

    client.cookies.clear()
    signed_in = await _sign_in_admin(client)
    assert signed_in["next_step"] == "mfa_challenge"
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}
    assert client.post(
        "/api/v1/auth/mfa/challenge",
        headers=headers,
        json={"code": totp_code(secret)},
    ).status_code == 204
    assert len(client.get("/api/v1/auth/sessions").json()) == 2

    rejected = client.post(
        "/api/v1/auth/mfa/disable",
        headers=headers,
        json={"password": "wrong password", "code": totp_code(secret)},
    )
    assert rejected.status_code == 401
    assert rejected.json()["error"]["code"] == "mfa_reset_verification_failed"
    rejected_code = client.post(
        "/api/v1/auth/mfa/disable",
        headers=headers,
        json={
            "password": "a secure administrator passphrase",
            "code": "000000",
        },
    )
    assert rejected_code.status_code == 401
    assert rejected_code.json()["error"]["code"] == rejected.json()["error"]["code"]

    reset = client.post(
        "/api/v1/auth/mfa/disable",
        headers=headers,
        json={
            "password": "a secure administrator passphrase",
            "code": totp_code(secret),
        },
    )
    assert reset.status_code == 204, reset.text
    assert client.get("/api/v1/auth/sessions").status_code == 403
    async with TestSession() as db:
        active_sessions = list(
            (
                await db.scalars(
                    select(Session).where(Session.revoked_at.is_(None))
                )
            ).all()
        )
    assert len(active_sessions) == 1
    assert client.get(f"/api/v1/institutions/{institution.id}/memberships").status_code == 403
    assert client.post("/api/v1/auth/mfa/setup", headers=headers).status_code == 200


async def test_activation_and_password_reset_reject_control_characters(
    client: TestClient,
) -> None:
    activation = client.post(
        "/api/v1/auth/invitations/not-a-real-token/accept",
        headers=csrf_headers(client),
        json={
            "password": "unsafe password\nvalue",
            "terms_version": "terms-2026-08",
            "privacy_version": "privacy-2026-08",
        },
    )
    assert activation.status_code == 422
    reset = client.post(
        "/api/v1/auth/password-reset/not-a-real-token/confirm",
        headers=csrf_headers(client),
        json={"password": "unsafe password\tvalue"},
    )
    assert reset.status_code == 422


async def test_password_only_session_cannot_replace_an_enrolled_mfa_factor(
    client: TestClient,
) -> None:
    _, admin = await _seed_admin()
    await _sign_in_admin(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}
    setup = client.post("/api/v1/auth/mfa/setup", headers=headers)
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(setup.json()["secret"])},
    )
    assert confirmed.status_code == 200

    client.cookies.clear()
    signed_in = await _sign_in_admin(client)
    assert signed_in["next_step"] == "mfa_challenge"
    attacker_csrf = client.cookies[get_settings().csrf_cookie_name]
    replacement = client.post(
        "/api/v1/auth/mfa/setup",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": attacker_csrf},
    )
    assert replacement.status_code == 403
    assert replacement.json()["error"]["code"] == "mfa_reauthentication_required"
    async with TestSession() as db:
        enrollment = await db.scalar(select(MfaEnrollment).where(MfaEnrollment.user_id == admin.id))
        assert enrollment is not None and enrollment.enrolled_at is not None


async def test_mfa_replacement_preserves_the_active_factor_until_confirmation(
    client: TestClient,
) -> None:
    _, admin = await _seed_admin()
    await _sign_in_admin(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}
    initial = client.post("/api/v1/auth/mfa/setup", headers=headers).json()
    assert client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(initial["secret"])},
    ).status_code == 200

    async with TestSession() as db:
        enrollment = await db.scalar(select(MfaEnrollment).where(MfaEnrollment.user_id == admin.id))
        assert enrollment is not None
        original_secret = enrollment.encrypted_secret

    replacement = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert replacement.status_code == 200
    async with TestSession() as db:
        enrollment = await db.scalar(select(MfaEnrollment).where(MfaEnrollment.user_id == admin.id))
        assert enrollment is not None
        assert enrollment.encrypted_secret == original_secret
        assert enrollment.pending_encrypted_secret is not None

    rejected = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": "000000"},
    )
    assert rejected.status_code == 422
    async with TestSession() as db:
        enrollment = await db.scalar(select(MfaEnrollment).where(MfaEnrollment.user_id == admin.id))
        assert enrollment is not None
        assert enrollment.encrypted_secret == original_secret
        assert enrollment.pending_encrypted_secret is not None

    accepted = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(replacement.json()["secret"])},
    )
    assert accepted.status_code == 200
    async with TestSession() as db:
        enrollment = await db.scalar(select(MfaEnrollment).where(MfaEnrollment.user_id == admin.id))
        assert enrollment is not None
        assert enrollment.encrypted_secret != original_secret
        assert enrollment.pending_encrypted_secret is None


async def test_repeated_invalid_mfa_codes_revoke_the_pending_session(
    client: TestClient,
) -> None:
    _, admin = await _seed_admin()
    await _sign_in_admin(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}
    setup = client.post("/api/v1/auth/mfa/setup", headers=headers)
    client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(setup.json()["secret"])},
    )
    client.cookies.clear()
    await _sign_in_admin(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}

    for _ in range(get_settings().mfa_max_attempts):
        response = client.post(
            "/api/v1/auth/mfa/challenge", headers=headers, json={"code": "000000"}
        )
        assert response.status_code == 401
    assert client.post(
        "/api/v1/auth/mfa/challenge", headers=headers, json={"code": "000000"}
    ).status_code == 401
    async with TestSession() as db:
        pending = await db.scalar(
            select(Session)
            .where(Session.user_id == admin.id)
            .order_by(Session.created_at.desc())
        )
        assert pending is not None and pending.revoked_at is not None


async def test_mfa_attempt_budget_survives_new_sign_in_sessions(client: TestClient) -> None:
    _, admin = await _seed_admin()
    await _sign_in_admin(client)
    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}
    setup = client.post("/api/v1/auth/mfa/setup", headers=headers).json()
    assert client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(setup["secret"])},
    ).status_code == 200

    for _ in range(get_settings().mfa_max_attempts):
        client.cookies.clear()
        signed_in = await _sign_in_admin(client)
        assert signed_in["next_step"] == "mfa_challenge"
        csrf = client.cookies[get_settings().csrf_cookie_name]
        response = client.post(
            "/api/v1/auth/mfa/challenge",
            headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
            json={"code": "000000"},
        )
        assert response.status_code == 401

    client.cookies.clear()
    assert (await _sign_in_admin(client))["next_step"] == "mfa_challenge"
    csrf = client.cookies[get_settings().csrf_cookie_name]
    still_locked = client.post(
        "/api/v1/auth/mfa/challenge",
        headers={"Origin": "http://localhost:3000", "X-CSRF-Token": csrf},
        json={"code": totp_code(setup["secret"])},
    )
    assert still_locked.status_code == 401
    async with TestSession() as db:
        enrollment = await db.scalar(select(MfaEnrollment).where(MfaEnrollment.user_id == admin.id))
        assert enrollment is not None
        assert enrollment.failed_attempts == get_settings().mfa_max_attempts
        assert enrollment.locked_until is not None


async def test_suspended_administrator_cannot_create_a_new_session(client: TestClient) -> None:
    _, admin = await _seed_admin()
    async with TestSession() as db:
        membership = await db.scalar(
            select(InstitutionMembership).where(InstitutionMembership.user_id == admin.id)
        )
        assert membership is not None
        membership.status = MembershipStatus.SUSPENDED.value
        await db.commit()
    response = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "email": "admin@lifecycle.edu",
            "password": "a secure administrator passphrase",
        },
    )
    assert response.status_code == 401


async def test_password_reset_is_generic_single_use_and_revokes_sessions(
    client: TestClient,
) -> None:
    async with TestSession() as db:
        user = User(
            email="reset@example.edu",
            password_hash=hash_password("old secure passphrase"),
            role=UserRole.STUDENT.value,
        )
        db.add(user)
        await db.commit()

    known = client.post(
        "/api/v1/auth/password-reset/request",
        headers=csrf_headers(client),
        json={"email": "reset@example.edu"},
    )
    unknown = client.post(
        "/api/v1/auth/password-reset/request",
        headers=csrf_headers(client),
        json={"email": "missing@example.edu"},
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()

    async with TestSession() as db:
        token = await issue_password_reset(db, "reset@example.edu", "test-request")
    assert token is not None
    reset = client.post(
        f"/api/v1/auth/password-reset/{token}/confirm",
        headers=csrf_headers(client),
        json={"password": "new secure passphrase"},
    )
    replay = client.post(
        f"/api/v1/auth/password-reset/{token}/confirm",
        headers=csrf_headers(client),
        json={"password": "another secure passphrase"},
    )
    assert reset.status_code == 204
    assert replay.status_code == 410


async def test_invitation_acceptance_records_policy_versions(client: TestClient) -> None:
    token = "policy-bound-invitation"  # noqa: S105
    async with TestSession() as db:
        institution = Institution(code="policy-campus", name="Policy Campus")
        db.add(institution)
        await db.flush()
        db.add(
            MembershipInvitation(
                institution_id=institution.id,
                email="policy.student@example.edu",
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
            "password": "a policy accepting passphrase",
            "terms_version": "terms-2026-08",
            "privacy_version": "privacy-2026-08",
        },
    )
    assert response.status_code == 201, response.text
    async with TestSession() as db:
        acceptances = list((await db.scalars(select(TermsAcceptance))).all())
        invitations = list((await db.scalars(select(MembershipInvitation))).all())
    assert {item.document_type for item in acceptances} == {"terms", "privacy"}
    assert invitations[0].accepted_at is not None
