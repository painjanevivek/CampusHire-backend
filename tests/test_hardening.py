from fastapi.testclient import TestClient

from app.core.resilience import CircuitBreaker
from app.main import app


def test_security_headers_are_present() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_ai_circuit_opens_without_blocking_core_domain() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.allow()
    breaker.record_success()
    assert breaker.allow()
