from fastapi.testclient import TestClient

from app.models.auth import InstitutionMembership, MembershipStatus, User, UserRole
from app.modules.auth.security import hash_password
from tests.test_auth import TestSession, client, csrf_headers, database, sign_in  # noqa: F401
from tests.test_platform_reports import seed_report


async def test_reviewer_can_decide_without_assignment_but_not_cross_institution(
    client: TestClient,  # noqa: F811
) -> None:
    colleges, application_ids, _ = await seed_report()
    async with TestSession() as db:
        reviewer = User(
            institution_id=colleges[0].id,
            email="reviewer@example.edu",
            username="reviewer",
            password_hash=hash_password("a reviewer passphrase"),
            role=UserRole.TNP_REVIEWER.value,
        )
        auditor = User(
            institution_id=colleges[0].id,
            email="decision-auditor@example.edu",
            username="decision-auditor",
            password_hash=hash_password("an auditor passphrase"),
            role=UserRole.TNP_AUDITOR.value,
        )
        db.add_all([reviewer, auditor])
        await db.flush()
        db.add_all([
            InstitutionMembership(
                institution_id=colleges[0].id, user_id=user.id,
                role=user.role, status=MembershipStatus.ACTIVE.value,
            )
            for user in (reviewer, auditor)
        ])
        await db.commit()

    sign_in(client, "reviewer", "a reviewer passphrase")
    base = "/api/v1/tnp/recruitment"
    queue = client.get(f"{base}/review-queue")
    assert queue.status_code == 200, queue.text
    assert queue.json()["total"] == 1
    detail = client.get(f"{base}/review-queue/{application_ids[0]}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["assignee_user_id"] is None
    assert client.get(f"{base}/applications/{application_ids[0]}/requests").status_code == 200
    decision = client.post(
        f"{base}/applications/{application_ids[0]}/decision",
        headers=csrf_headers(client),
        json={
            "expected_revision": detail.json()["revision"],
            "status": "offered",
            "reason": "Selected after the documented interview review.",
        },
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["status"] == "offered"
    assert decision.json()["history"][-1]["actor_display_name"] == "reviewer"
    assert decision.json()["history"][-1]["reason"] == (
        "Selected after the documented interview review."
    )
    stale = client.post(
        f"{base}/applications/{application_ids[0]}/decision",
        headers=csrf_headers(client),
        json={
            "expected_revision": detail.json()["revision"],
            "status": "rejected",
            "reason": "A different documented outcome was recorded.",
        },
    )
    assert stale.status_code == 409
    outside = client.post(
        f"{base}/applications/{application_ids[1]}/decision",
        headers=csrf_headers(client),
        json={
            "expected_revision": 1,
            "status": "rejected",
            "reason": "A different documented outcome was recorded.",
        },
    )
    assert outside.status_code == 404

    client.cookies.clear()
    sign_in(client, "decision-auditor", "an auditor passphrase")
    denied = client.post(
        f"{base}/applications/{application_ids[0]}/decision",
        headers=csrf_headers(client),
        json={
            "expected_revision": decision.json()["revision"],
            "status": "rejected",
            "reason": "A different documented outcome was recorded.",
        },
    )
    assert denied.status_code == 403
