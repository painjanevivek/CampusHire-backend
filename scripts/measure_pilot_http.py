from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    method: str
    path: str
    samples: int
    concurrency: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    error_rate: float
    status_counts: dict[str, int]
    budget_p95_ms: int
    passed: bool


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile_value
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


async def authenticate(client: httpx.AsyncClient, email: str, password: str) -> str:
    csrf_response = await client.get("/auth/csrf")
    csrf_response.raise_for_status()
    csrf_token = client.cookies.get("campushire_csrf")
    if not csrf_token:
        raise RuntimeError("The API did not issue a CSRF cookie.")
    response = await client.post(
        "/auth/sign-in",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": email, "password": password},
    )
    response.raise_for_status()
    refreshed_token = client.cookies.get("campushire_csrf")
    if not refreshed_token:
        raise RuntimeError("The authenticated session did not retain a CSRF cookie.")
    return refreshed_token


async def measure(
    *,
    client: httpx.AsyncClient,
    name: str,
    method: str,
    path: str,
    samples: int,
    concurrency: int,
    budget_p95_ms: int,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    warmup: bool = True,
) -> ScenarioResult:
    semaphore = asyncio.Semaphore(concurrency)

    async def request_once() -> tuple[float, int]:
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await client.request(
                    method,
                    path,
                    headers=headers,
                    json=json_body,
                )
                status = response.status_code
                await response.aread()
            except httpx.HTTPError:
                status = 0
            elapsed_ms = (time.perf_counter() - started) * 1000
            return elapsed_ms, status

    if warmup:
        await request_once()
    observations = await asyncio.gather(*(request_once() for _ in range(samples)))
    timings = [item[0] for item in observations]
    status_counts = Counter(str(item[1]) for item in observations)
    failures = sum(count for status, count in status_counts.items() if not status.startswith("2"))
    p95_ms = percentile(timings, 0.95)
    error_rate = failures / samples
    return ScenarioResult(
        name=name,
        method=method,
        path=path,
        samples=samples,
        concurrency=concurrency,
        p50_ms=round(statistics.median(timings), 2),
        p95_ms=round(p95_ms, 2),
        p99_ms=round(percentile(timings, 0.99), 2),
        max_ms=round(max(timings), 2),
        error_rate=round(error_rate, 4),
        status_counts=dict(status_counts),
        budget_p95_ms=budget_p95_ms,
        passed=error_rate == 0 and p95_ms <= budget_p95_ms,
    )


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} in the process environment before running the baseline.")
    return value


async def run(args: argparse.Namespace) -> dict[str, Any]:
    origin = args.origin.rstrip("/")
    common = {
        "base_url": args.base_url.rstrip("/"),
        "headers": {"Origin": origin},
        "timeout": httpx.Timeout(args.timeout_seconds),
        "limits": httpx.Limits(
            max_connections=max(args.concurrency * 2, 10),
            max_keepalive_connections=max(args.concurrency, 5),
        ),
    }
    scenarios: list[ScenarioResult] = []

    async with (
        httpx.AsyncClient(**common) as public_client,
        httpx.AsyncClient(**common) as student_client,
        httpx.AsyncClient(**common) as admin_client,
    ):
        student_csrf = await authenticate(
            student_client,
            required_environment("PILOT_STUDENT_EMAIL"),
            required_environment("PILOT_STUDENT_PASSWORD"),
        )
        await authenticate(
            admin_client,
            required_environment("PILOT_ADMIN_EMAIL"),
            required_environment("PILOT_ADMIN_PASSWORD"),
        )

        definitions = [
            (public_client, "health_live", "GET", "/health/live", 250),
            (student_client, "student_dashboard", "GET", "/dashboard", 1000),
            (
                student_client,
                "opportunity_search_with_eligibility",
                "GET",
                "/opportunities",
                1000,
            ),
            (student_client, "notification_feed", "GET", "/notifications", 750),
            (
                admin_client,
                "admin_worker_summary",
                "GET",
                "/admin/operations/summary",
                750,
            ),
            (
                admin_client,
                "admin_worker_history",
                "GET",
                "/admin/operations/resume-jobs",
                1000,
            ),
        ]
        for client, name, method, path, budget in definitions:
            scenarios.append(
                await measure(
                    client=client,
                    name=name,
                    method=method,
                    path=path,
                    samples=args.samples,
                    concurrency=args.concurrency,
                    budget_p95_ms=budget,
                )
            )

        role_id = os.getenv("PILOT_ROLE_ID")
        resume_version_id = os.getenv("PILOT_RESUME_VERSION_ID")
        skipped: list[dict[str, str]] = []
        if role_id and resume_version_id:
            idempotency_key = f"pilot-baseline-{time.time_ns()}"
            application_headers = {
                "X-CSRF-Token": student_csrf,
                "Idempotency-Key": idempotency_key,
            }
            application_body = {
                "role_id": role_id,
                "resume_version_id": resume_version_id,
            }
            scenarios.append(
                await measure(
                    client=student_client,
                    name="application_initial_submission",
                    method="POST",
                    path="/applications",
                    samples=1,
                    concurrency=1,
                    budget_p95_ms=1500,
                    headers=application_headers,
                    json_body=application_body,
                    warmup=False,
                )
            )
            scenarios.append(
                await measure(
                    client=student_client,
                    name="idempotent_application_replay",
                    method="POST",
                    path="/applications",
                    samples=args.samples,
                    concurrency=args.concurrency,
                    budget_p95_ms=1500,
                    headers=application_headers,
                    json_body=application_body,
                )
            )
        else:
            skipped.append(
                {
                    "name": "idempotent_application_submission",
                    "reason": "PILOT_ROLE_ID and PILOT_RESUME_VERSION_ID were not supplied.",
                }
            )

    return {
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment_label": args.environment_label,
        "base_url": args.base_url,
        "samples_per_scenario": args.samples,
        "concurrency": args.concurrency,
        "budgets": "provisional pre-pilot engineering gates; institutional SLO approval pending",
        "scenarios": [asdict(item) for item in scenarios],
        "skipped": skipped,
        "passed": all(item.passed for item in scenarios),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure repeatable CampusHire pilot HTTP baselines."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--origin", default="http://127.0.0.1:3000")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--environment-label",
        default="local-development-not-production-capacity",
    )
    parser.add_argument("--output", default=".data/pilot-http-baseline.json")
    args = parser.parse_args()
    if args.samples < 5 or args.concurrency < 1:
        parser.error("Use at least 5 samples and concurrency of 1 or greater.")
    return args


def main() -> None:
    args = parse_args()
    result = asyncio.run(run(args))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
