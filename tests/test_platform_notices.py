from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models.auth import (
    Institution,
    InstitutionMembership,
    MembershipStatus,
    MfaEnrollment,
    Session,
    User,
    UserRole,
)
from app.models.engagement import InAppNotification
from app.modules.auth.security import decrypt_totp_secret, hash_password, totp_code
from tests.test_auth import (  # noqa: F401
    TestSession,
    client,
    csrf_headers,
    database,
    seed_platform_admin,
    sign_in,
)

pytestmark = pytest.mark.asyncio


async def seed_recipients() -> tuple[list[Institution], list[User], list[User]]:
    async with TestSession() as db:
        colleges = [
            Institution(code=code, name=name)
            for code, name in (
                ("pccoe-pune", "PCCOE"),
                ("pccoer-pune", "PCCOE&R"),
                ("nmiet-pune", "NMIET"),
                ("ncer-pune", "NCER"),
                ("pcu-pune", "PCU"),
            )
        ]
        db.add_all(colleges)
        await db.flush()
        students = []
        officers = []
        for index, college in enumerate(colleges):
            student = User(
                institution_id=college.id,
                email=f"student{index}@example.edu",
                password_hash=hash_password("a secure student passphrase"),
                role=UserRole.STUDENT.value,
            )
            officer = User(
                institution_id=college.id,
                email=f"officer{index}@example.edu",
                username=f"officer{index}",
                password_hash=hash_password("a secure officer passphrase"),
                role=UserRole.TNP_ADMIN.value,
            )
            students.append(student)
            officers.append(officer)
            db.add_all([student, officer])
        await db.flush()
        for college, student, officer in zip(colleges, students, officers, strict=True):
            db.add_all(
                [
                    InstitutionMembership(
                        institution_id=college.id,
                        user_id=student.id,
                        role=UserRole.STUDENT.value,
                        status=MembershipStatus.ACTIVE.value,
                    ),
                    InstitutionMembership(
                        institution_id=college.id,
                        user_id=officer.id,
                        role=UserRole.TNP_ADMIN.value,
                        status=MembershipStatus.ACTIVE.value,
                    ),
                ]
            )
        await db.commit()
        return colleges, students, officers


async def test_platform_notices_reach_only_selected_audience_and_account_inboxes(
    client: TestClient,  # noqa: F811
) -> None:
    await seed_platform_admin()
    _, students, officers = await seed_recipients()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    student_notice = client.post(
        "/api/v1/platform/notices",
        headers=csrf_headers(client),
        json={"subject": "Student notice", "message": "Read the platform update.",
              "to_students": True, "to_tnp": False},
    )
    assert student_notice.status_code == 201, student_notice.text
    assert student_notice.json()["student_recipients"] == 5
    assert student_notice.json()["tnp_recipients"] == 0
    officer_notice = client.post(
        "/api/v1/platform/notices",
        headers=csrf_headers(client),
        json={"subject": "Officer notice", "message": "Review the platform update.",
              "to_students": False, "to_tnp": True},
    )
    assert officer_notice.status_code == 201, officer_notice.text
    assert officer_notice.json()["student_recipients"] == 0
    assert officer_notice.json()["tnp_recipients"] == 5

    async with TestSession() as db:
        delivered = (await db.scalars(select(InAppNotification))).all()
        assert len(delivered) == 10
        assert {item.recipient_user_id for item in delivered if item.title == "Student notice"} == {
            student.id for student in students
        }
        assert {item.recipient_user_id for item in delivered if item.title == "Officer notice"} == {
            officer.id for officer in officers
        }

    client.cookies.clear()
    sign_in(client, students[0].email, "a secure student passphrase")
    inbox = client.get("/api/v1/account/notifications")
    assert inbox.status_code == 200, inbox.text
    assert [item["title"] for item in inbox.json()["items"]] == ["Student notice"]
    notification_id = inbox.json()["items"][0]["id"]
    marked = client.post(
        f"/api/v1/account/notifications/{notification_id}/read",
        headers=csrf_headers(client),
    )
    assert marked.status_code == 200, marked.text
    assert client.get("/api/v1/account/notifications").json()["unread_count"] == 0

    client.cookies.clear()
    sign_in(client, officers[0].username or "", "a secure officer passphrase")
    officer_inbox = client.get("/api/v1/account/notifications")
    assert officer_inbox.status_code == 200, officer_inbox.text
    assert [item["title"] for item in officer_inbox.json()["items"]] == ["Officer notice"]
    denied = client.post(
        f"/api/v1/account/notifications/{notification_id}/read",
        headers=csrf_headers(client),
    )
    assert denied.status_code == 404
    cannot_broadcast = client.post(
        "/api/v1/platform/notices",
        headers=csrf_headers(client),
        json={"subject": "Forged notice", "message": "Should never be sent.",
              "to_students": True},
    )
    assert cannot_broadcast.status_code == 403


async def test_staff_provisioning_works_for_every_college_after_recent_mfa(
    client: TestClient,  # noqa: F811
) -> None:
    admin = await seed_platform_admin()
    colleges, _, _ = await seed_recipients()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    setup = client.post("/api/v1/auth/mfa/setup", headers=csrf_headers(client))
    assert setup.status_code == 200, setup.text
    confirmed = client.post(
        "/api/v1/auth/mfa/confirm",
        headers=csrf_headers(client),
        json={"code": totp_code(setup.json()["secret"])},
    )
    assert confirmed.status_code == 200, confirmed.text
    async with TestSession() as db:
        session = await db.scalar(
            select(Session).where(Session.user_id == admin.id, Session.revoked_at.is_(None))
        )
        enrollment = await db.scalar(
            select(MfaEnrollment).where(MfaEnrollment.user_id == admin.id)
        )
        assert session is not None and enrollment is not None
        secret = decrypt_totp_secret(enrollment.encrypted_secret)
        session.mfa_verified_at = datetime.now(UTC) - timedelta(minutes=11)
        await db.commit()

    path = f"/api/v1/platform/institutions/{colleges[0].id}/staff-accounts"
    payload = {
        "username": "new-officer-0",
        "password": "a secure initial passphrase",
        "role": "tnp_reviewer",
        "reason": "Assigned to the verified college placement team.",
    }
    blocked = client.post(path, headers=csrf_headers(client), json=payload)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "reauthentication_required"
    verified = client.post(
        "/api/v1/auth/mfa/challenge",
        headers=csrf_headers(client),
        json={"code": totp_code(secret)},
    )
    assert verified.status_code == 204, verified.text
    for index, college in enumerate(colleges):
        created = client.post(
            f"/api/v1/platform/institutions/{college.id}/staff-accounts",
            headers=csrf_headers(client),
            json={**payload, "username": f"new-officer-{index}"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["institution_id"] == str(college.id)

    async with TestSession() as db:
        memberships = (
            await db.scalars(
                select(InstitutionMembership).where(
                    InstitutionMembership.user_id.in_(
                        select(User.id).where(User.username.like("new-officer-%"))
                    )
                )
            )
        ).all()
        assert {membership.institution_id for membership in memberships} == {
            college.id for college in colleges
        }


async def test_notice_requires_an_audience(client: TestClient) -> None:  # noqa: F811
    await seed_platform_admin()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    response = client.post(
        "/api/v1/platform/notices",
        headers=csrf_headers(client),
        json={"subject": "Empty audience", "message": "No recipients were selected."},
    )
    assert response.status_code == 422


async def test_notice_can_reach_both_audiences(client: TestClient) -> None:  # noqa: F811
    await seed_platform_admin()
    await seed_recipients()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    response = client.post(
        "/api/v1/platform/notices",
        headers=csrf_headers(client),
        json={
            "subject": "All account update",
            "message": "CampusHire will be updated this weekend.",
            "to_students": True,
            "to_tnp": True,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["student_recipients"] == 5
    assert response.json()["tnp_recipients"] == 5


async def test_platform_admin_can_add_institute_and_receive_activation_handoff(
    client: TestClient,  # noqa: F811
) -> None:
    await seed_platform_admin()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    response = client.post(
        "/api/v1/platform/institutions",
        headers=csrf_headers(client),
        json={
            "institution_code": "new-college-pune",
            "institution_name": "New College of Engineering, Pune",
            "admin_email": "officer@new-college.example",
        },
    )
    assert response.status_code == 201, response.text
    handoff = response.json()
    assert handoff["admin_invitation_token"]
    assert response.headers["cache-control"] == "no-store"

    async with TestSession() as db:
        institution = await db.scalar(
            select(Institution).where(Institution.code == "new-college-pune")
        )
        assert institution is not None
        assert str(institution.id) == handoff["institution_id"]

    duplicate = client.post(
        "/api/v1/platform/institutions",
        headers=csrf_headers(client),
        json={
            "institution_code": "new-college-pune",
            "institution_name": "New College of Engineering, Pune",
            "admin_email": "another-officer@new-college.example",
        },
    )
    assert duplicate.status_code == 409
