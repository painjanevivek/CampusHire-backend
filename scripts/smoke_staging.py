from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

import httpx


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} before running the synthetic staging smoke.")
    return value


async def authenticate(client: httpx.AsyncClient, email: str, password: str) -> None:
    response = await client.get("/api/v1/auth/csrf")
    response.raise_for_status()
    token = client.cookies.get("campushire_csrf")
    if not token:
        raise AssertionError("CSRF cookie was not issued")
    signed_in = await client.post(
        "/api/v1/auth/sign-in",
        headers={"X-CSRF-Token": token},
        json={"email": email, "password": password},
    )
    signed_in.raise_for_status()


def assert_headers(response: httpx.Response, *, frontend: bool) -> None:
    assert response.headers.get("strict-transport-security", "").startswith("max-age=31536000")
    assert response.headers.get("x-content-type-options") == "nosniff"
    policy = response.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in policy
    assert "default-src 'self'" in policy if frontend else "default-src 'none'" in policy


async def run(args: argparse.Namespace) -> dict[str, Any]:
    origin = args.base_url.rstrip("/")
    common: dict[str, Any] = {
        "base_url": origin,
        "headers": {"Origin": origin},
        "follow_redirects": False,
        "timeout": 15,
        "verify": not args.insecure_local_tls,
    }
    checks: list[str] = []
    async with (
        httpx.AsyncClient(**common) as public,
        httpx.AsyncClient(**common) as student,
        httpx.AsyncClient(**common) as admin,
    ):
        landing = await public.get("/")
        landing.raise_for_status()
        assert_headers(landing, frontend=True)
        checks.append("https_frontend_headers")

        for path in ("/api/v1/health/live", "/api/v1/health/ready"):
            response = await public.get(path)
            response.raise_for_status()
            assert_headers(response, frontend=False)
        checks.append("api_health_and_headers")

        await authenticate(
            student,
            os.getenv("STAGING_STUDENT_EMAIL", "student+synthetic-a@example.com"),
            required("STAGING_STUDENT_PASSWORD"),
        )
        me = await student.get("/api/v1/auth/me")
        me.raise_for_status()
        dashboard = await student.get("/api/v1/dashboard")
        dashboard.raise_for_status()
        checks.append("student_session_and_dashboard")

        await authenticate(
            admin,
            os.getenv("STAGING_ADMIN_EMAIL", "admin+synthetic-a@example.com"),
            required("STAGING_ADMIN_PASSWORD"),
        )
        operations = await admin.get("/api/v1/admin/operations/summary")
        operations.raise_for_status()
        checks.append("administrator_operations")

        other_institution = required("STAGING_SECOND_INSTITUTION_ID")
        denied = await admin.get(f"/api/v1/institutions/{other_institution}/memberships")
        assert denied.status_code == 403, denied.text
        checks.append("cross_tenant_access_denied")

    return {
        "environment": args.environment_label,
        "data_class": "synthetic-only",
        "checks": checks,
        "passed": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run production-like synthetic staging smoke checks"
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--environment-label", required=True)
    parser.add_argument(
        "--insecure-local-tls",
        action="store_true",
        help="Allow only an explicitly labelled local internal-CA rehearsal.",
    )
    args = parser.parse_args()
    if args.insecure_local_tls and not args.environment_label.startswith("local-"):
        parser.error("--insecure-local-tls requires an environment label beginning with 'local-'")
    return args


def main() -> None:
    result = asyncio.run(run(parse_args()))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
