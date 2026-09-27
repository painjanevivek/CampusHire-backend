import pymupdf
import pytest
from fastapi.testclient import TestClient

from tests.test_auth import client, csrf_headers, database, sign_in  # noqa: F401
from tests.test_platform_notices import seed_recipients

pytestmark = pytest.mark.asyncio


async def test_marksheet_upload_is_optional_and_student_private(
    client: TestClient,  # noqa: F811
) -> None:
    _, students, _ = await seed_recipients()
    sign_in(client, students[0].email, "a secure student passphrase")
    assert client.get("/api/v1/onboarding/academic-documents").json()["class_10"] is False

    document = pymupdf.open()
    document.new_page()
    uploaded = client.put(
        "/api/v1/onboarding/academic-documents/class_10",
        headers=csrf_headers(client),
        files={"file": ("class-10.pdf", document.tobytes(), "application/pdf")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.get("/api/v1/onboarding/academic-documents").json()["class_10"] is True
    downloaded = client.get("/api/v1/onboarding/academic-documents/class_10")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF-")
    assert downloaded.headers["cache-control"] == "private, no-store"

    client.cookies.clear()
    sign_in(client, students[1].email, "a secure student passphrase")
    assert client.get("/api/v1/onboarding/academic-documents/class_10").status_code == 404

    client.cookies.clear()
    sign_in(client, students[0].email, "a secure student passphrase")
    removed = client.delete(
        "/api/v1/onboarding/academic-documents/class_10", headers=csrf_headers(client)
    )
    assert removed.status_code == 204
    assert client.get("/api/v1/onboarding/academic-documents").json()["class_10"] is False
