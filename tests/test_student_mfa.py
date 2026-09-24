# ruff: noqa: F811

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models.auth import (
    Institution,
    InstitutionDomain,
    InstitutionMembership,
    MembershipStatus,
    User,
    UserRole,
)
from app.models.profile import StudentProfile
from app.modules.auth.security import hash_password, totp_code
from tests.test_auth import TestSession, client, csrf_headers, database  # noqa: F401

pytestmark = pytest.mark.asyncio


async def _seed_student(email: str = "student23@pccoepune.org") -> User:
    async with TestSession() as db:
        institution = Institution(code="pccoe-student-mfa", name="PCCOE")
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
        user = User(
            email=email,
            password_hash=hash_password("a secure student passphrase"),
            role=UserRole.STUDENT.value,
            institution_id=institution.id,
        )
        db.add(user)
        await db.flush()
        db.add_all(
            [
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=user.id,
                    role=UserRole.STUDENT.value,
                    status=MembershipStatus.ACTIVE.value,
                    verified_at=datetime.now(UTC),
                ),
                StudentProfile(
                    user_id=user.id,
                    institution_id=institution.id,
                    prn="123B1B287",
                ),
            ]
        )
        await db.commit()
        return user


async def test_pccoe_student_signup_enforces_email_without_paid_verification(
    client: TestClient,
) -> None:
    async with TestSession() as db:
        institution = Institution(code="pccoe-public-signup", name="PCCOE")
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
        institution_id = institution.id

    payload = {
        "name": "Asha",
        "surname": "Patil",
        "dob": "2005-01-02",
        "email": "  ASHA.PATIL23@PCCOEPUNE.ORG  ",
        "institution_id": str(institution_id),
        "password": "a secure student passphrase",
        "re_enter_password": "a secure student passphrase",
        "terms_version": "2026-08-28",
        "privacy_version": "2026-08-28",
    }
    response = client.post("/api/v1/auth/signup", headers=csrf_headers(client), json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "registered"
    assert client.get("/api/v1/auth/me").status_code == 200
    async with TestSession() as db:
        user = await db.scalar(select(User).where(User.email == "asha.patil23@pccoepune.org"))
        assert user is not None

    client.cookies.clear()
    payload["email"] = "asha.patil@gmail.com"
    rejected = client.post("/api/v1/auth/signup", headers=csrf_headers(client), json=payload)
    assert rejected.status_code == 422


async def test_student_mfa_challenge_is_server_enforced_and_recovery_is_single_use(
    client: TestClient,
) -> None:
    student = await _seed_student()
    signed_in = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": student.email,
            "password": "a secure student passphrase",
            "workspace": "student",
        },
    )
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["next_step"] == "complete"

    mismatch = client.patch(
        "/api/v1/profile",
        headers=csrf_headers(client),
        json={"prn": "124B1B287"},
    )
    assert mismatch.status_code == 422
    assert "does not match your PRN" in mismatch.json()["error"]["message"]

    csrf = client.cookies[get_settings().csrf_cookie_name]
    headers = {"Origin": "http://localhost:3000", "X-CSRF-Token": csrf}
    setup = client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    assert setup.json()["provisioning_uri"].startswith("otpauth://totp/CampusHire%20AI:")
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=headers,
        json={"code": totp_code(setup.json()["secret"])},
    )
    assert confirmed.status_code == 200, confirmed.text
    recovery_code = confirmed.json()["recovery_codes"][0]
    secret = setup.json()["secret"]
    profile = client.get("/api/v1/profile")
    assert profile.status_code == 200
    assert "encrypted_secret" not in profile.text
    assert secret not in profile.text

    client.cookies.clear()
    challenge_sign_in = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": student.email,
            "password": "a secure student passphrase",
            "workspace": "student",
        },
    )
    assert challenge_sign_in.json()["next_step"] == "mfa_challenge"
    assert client.get("/api/v1/profile").status_code == 403
    headers = csrf_headers(client)
    invalid = client.post(
        "/api/v1/auth/mfa/challenge",
        headers=headers,
        json={"code": "000000"},
    )
    assert invalid.status_code == 401
    verified = client.post(
        "/api/v1/auth/mfa/challenge",
        headers=csrf_headers(client),
        json={"code": totp_code(secret)},
    )
    assert verified.status_code == 204
    assert client.get("/api/v1/profile").status_code == 200

    client.cookies.clear()
    challenge_sign_in = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": student.email,
            "password": "a secure student passphrase",
            "workspace": "student",
        },
    )
    assert challenge_sign_in.json()["next_step"] == "mfa_challenge"
    headers = csrf_headers(client)
    first_use = client.post(
        "/api/v1/auth/mfa/challenge",
        headers=headers,
        json={"code": recovery_code},
    )
    assert first_use.status_code == 204
    client.cookies.clear()
    challenge_sign_in = client.post(
        "/api/v1/auth/sign-in",
        headers=csrf_headers(client),
        json={
            "identifier": student.email,
            "password": "a secure student passphrase",
            "workspace": "student",
        },
    )
    replay = client.post(
        "/api/v1/auth/mfa/challenge",
        headers=csrf_headers(client),
        json={"code": recovery_code},
    )
    assert challenge_sign_in.json()["next_step"] == "mfa_challenge"
    assert replay.status_code == 401
