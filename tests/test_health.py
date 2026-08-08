from fastapi.testclient import TestClient

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
