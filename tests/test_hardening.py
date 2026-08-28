from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.core.config import get_settings
from app.core.rate_limit import enforce_fixed_window_limit
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


class UnavailableRedis:
    @classmethod
    def from_url(cls, *_: object, **__: object) -> "UnavailableRedis":
        return cls()

    async def __aenter__(self) -> "UnavailableRedis":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def incr(self, _: str) -> int:
        raise OSError("redis unavailable")


def request_for(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


async def test_expensive_operation_budget_is_enforced_during_local_redis_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limit, "Redis", UnavailableRedis)
    rate_limit._fallback.clear()
    request = request_for("/api/v1/opportunities/role-1/match")
    await enforce_fixed_window_limit(
        request,
        namespace="semantic-match",
        identity="institution:student",
        limit=1,
        unavailable_detail="Semantic matching is temporarily unavailable",
    )
    with pytest.raises(HTTPException) as error:
        await enforce_fixed_window_limit(
            request,
            namespace="semantic-match",
            identity="institution:student",
            limit=1,
            unavailable_detail="Semantic matching is temporarily unavailable",
        )
    assert error.value.status_code == 429


async def test_expensive_operation_fails_closed_in_production_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limit, "Redis", UnavailableRedis)
    monkeypatch.setattr(
        rate_limit,
        "get_settings",
        lambda: SimpleNamespace(redis_url="redis://unavailable", is_development=False),
    )
    with pytest.raises(HTTPException) as error:
        await enforce_fixed_window_limit(
            request_for("/api/v1/opportunities/role-1/match"),
            namespace="semantic-match",
            identity="institution:student",
            limit=10,
            unavailable_detail="Semantic matching is temporarily unavailable",
        )
    assert error.value.status_code == 503


def test_semantic_match_contract_is_a_csrf_protected_mutation() -> None:
    operation = app.openapi()["paths"]["/api/v1/opportunities/{role_id}/match"]
    assert "post" in operation
    assert "get" not in operation


def test_request_logs_use_route_templates_instead_of_bearer_tokens(
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "secret-reset-capability"  # noqa: S105
    with TestClient(app) as client:
        client.post(
            f"/api/v1/auth/password-reset/{token}/confirm",
            json={"password": "a replacement passphrase"},
        )
    logs = [
        line
        for line in capsys.readouterr().err.splitlines()
        if '"logger": "app.core.middleware"' in line
    ]
    assert all(token not in line for line in logs)
    assert any('"route": "/auth/password-reset/{token}/confirm"' in line for line in logs)


def test_oversized_resume_body_is_rejected_before_route_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESUME_MAX_BYTES", "1024")
    monkeypatch.setenv("REQUEST_BODY_OVERHEAD_BYTES", "1024")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/resumes",
                files={"file": ("large.pdf", b"%PDF" + b"x" * 4096, "application/pdf")},
            )
        assert response.status_code == 413
    finally:
        get_settings.cache_clear()
