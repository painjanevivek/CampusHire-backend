import json
import logging

from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from app.main import app


def test_liveness() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


def test_valid_request_id_is_propagated() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health/live",
            headers={"X-Request-ID": "smoke-test-123"},
        )

    assert response.headers["X-Request-ID"] == "smoke-test-123"


def test_api_security_headers_are_present() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Cross-Origin-Resource-Policy"] == "same-site"
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    )


def test_structured_logs_redact_credentials_and_ignore_unknown_pii_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="campushire.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="student@example.edu token=super-secret Bearer abc.def",
        args=(),
        exc_info=None,
    )
    record.correlation_id = "security-test-123"
    record.student_email = "ignored@example.edu"

    payload = json.loads(formatter.format(record))

    assert payload["message"] == (
        "[redacted-email] token=[redacted] Bearer [redacted]"
    )
    assert payload["correlation_id"] == "security-test-123"
    assert "student_email" not in payload
