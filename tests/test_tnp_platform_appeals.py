import pytest
from fastapi.testclient import TestClient

from tests.test_auth import (  # noqa: F401
    client,
    csrf_headers,
    database,
    seed_platform_admin,
    sign_in,
)
from tests.test_platform_notices import seed_recipients

pytestmark = pytest.mark.asyncio


async def test_tnp_officer_appeal_reaches_platform_admin_and_can_be_resolved(
    client: TestClient,  # noqa: F811
) -> None:
    await seed_platform_admin()
    _, students, officers = await seed_recipients()
    sign_in(client, officers[0].username or "", "a secure officer passphrase")
    created = client.post(
        "/api/v1/tnp/platform-appeals",
        headers=csrf_headers(client),
        json={"subject": "Access issue", "description": "Please review the account access issue."},
    )
    assert created.status_code == 201, created.text
    appeal_id = created.json()["id"]
    assert created.json()["status"] == "open"
    assert client.get("/api/v1/tnp/platform-appeals").json()["items"][0]["id"] == appeal_id

    client.cookies.clear()
    sign_in(client, students[0].email, "a secure student passphrase")
    assert client.post(
        "/api/v1/tnp/platform-appeals",
        headers=csrf_headers(client),
        json={"subject": "Forged", "description": "Should be denied."},
    ).status_code == 403

    client.cookies.clear()
    sign_in(client, "platform-admin", "a secure platform passphrase")
    inbox = client.get("/api/v1/platform/tnp-appeals")
    assert inbox.status_code == 200, inbox.text
    assert inbox.json()["items"][0]["id"] == appeal_id
    assert inbox.json()["items"][0]["submitted_by"] == officers[0].email
    notifications = client.get("/api/v1/account/notifications")
    assert any(
        item["title"] == "T&P appeal: Access issue"
        for item in notifications.json()["items"]
    )
    resolved = client.patch(
        f"/api/v1/platform/tnp-appeals/{appeal_id}",
        headers=csrf_headers(client),
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
