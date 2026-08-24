from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from app.modules.resumes.builder import ResumeContent, generate_pdf


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    method: str
    path: str
    samples: int
    rounds: int
    concurrency: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    total_duration_ms: float
    throughput_rps: float
    error_rate: float
    status_counts: dict[str, int]
    budget_p95_ms: int
    passed: bool


@dataclass(frozen=True)
class WorkerThroughputResult:
    submitted_jobs: int
    completed_jobs: int
    terminal_status_counts: dict[str, int]
    total_duration_ms: float
    throughput_jobs_per_second: float
    job_duration_p50_ms: float
    job_duration_p95_ms: float
    uploaded_bytes: int
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
    rounds: int,
    concurrency: int,
    budget_p95_ms: int,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    expected_json: dict[str, Any] | None = None,
    warmup: bool = True,
) -> ScenarioResult:
    semaphore = asyncio.Semaphore(concurrency)

    async def request_once() -> tuple[float, str]:
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
                if expected_json is not None and any(
                    response.json().get(key) != value for key, value in expected_json.items()
                ):
                    status_label = f"{status}:unexpected-body"
                else:
                    status_label = str(status)
            except (httpx.HTTPError, ValueError):
                status_label = "0"
            elapsed_ms = (time.perf_counter() - started) * 1000
            return elapsed_ms, status_label

    if warmup:
        await request_once()
    started = time.perf_counter()
    observations: list[tuple[float, str]] = []
    for _ in range(rounds):
        observations.extend(await asyncio.gather(*(request_once() for _ in range(samples))))
    total_duration_ms = (time.perf_counter() - started) * 1_000
    timings = [item[0] for item in observations]
    status_counts = Counter(item[1] for item in observations)
    failures = sum(
        count
        for status, count in status_counts.items()
        if len(status) != 3 or not status.startswith("2")
    )
    p95_ms = percentile(timings, 0.95)
    error_rate = failures / len(observations)
    return ScenarioResult(
        name=name,
        method=method,
        path=path,
        samples=samples,
        rounds=rounds,
        concurrency=concurrency,
        p50_ms=round(statistics.median(timings), 2),
        p95_ms=round(p95_ms, 2),
        p99_ms=round(percentile(timings, 0.99), 2),
        max_ms=round(max(timings), 2),
        total_duration_ms=round(total_duration_ms, 2),
        throughput_rps=round(len(observations) / (total_duration_ms / 1_000), 2),
        error_rate=round(error_rate, 4),
        status_counts=dict(status_counts),
        budget_p95_ms=budget_p95_ms,
        passed=error_rate == 0 and p95_ms <= budget_p95_ms,
    )


async def measure_worker_throughput(
    *,
    client: httpx.AsyncClient,
    csrf_token: str,
    samples: int,
    timeout_seconds: float,
) -> WorkerThroughputResult:
    started = time.perf_counter()
    resume_ids: list[str] = []
    uploaded_bytes = 0
    for index in range(samples):
        pdf = generate_pdf(
            ResumeContent(
                full_name=f"Synthetic Worker Sample {index + 1}",
                email=f"worker-sample-{index + 1}@example.com",
                summary="Synthetic evidence for bounded worker throughput measurement.",
                skills=["Python", "SQL"],
            )
        )
        uploaded_bytes += len(pdf)
        response = await client.post(
            "/resumes",
            headers={"X-CSRF-Token": csrf_token},
            files={"file": (f"synthetic-worker-{index + 1}.pdf", pdf, "application/pdf")},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("duplicate") or not payload.get("id"):
            raise RuntimeError("Worker throughput samples must create distinct resume versions.")
        resume_ids.append(str(payload["id"]))

    deadline = time.monotonic() + timeout_seconds
    terminal: dict[str, dict[str, Any]] = {}
    while len(terminal) < len(resume_ids):
        for resume_id in resume_ids:
            if resume_id in terminal:
                continue
            response = await client.get(f"/resumes/{resume_id}")
            response.raise_for_status()
            payload = response.json()
            if payload["status"] in {"review_required", "completed", "failed", "cancelled"}:
                terminal[resume_id] = payload
        if len(terminal) == len(resume_ids):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Resume jobs did not reach a terminal state within the budget.")
        await asyncio.sleep(0.25)

    total_duration_ms = (time.perf_counter() - started) * 1_000
    statuses = Counter(str(item["status"]) for item in terminal.values())
    durations = [
        float(item["job"]["duration_ms"])
        for item in terminal.values()
        if item.get("job") and item["job"].get("duration_ms") is not None
    ]
    successful = sum(statuses.get(status, 0) for status in ("review_required", "completed"))
    return WorkerThroughputResult(
        submitted_jobs=len(resume_ids),
        completed_jobs=successful,
        terminal_status_counts=dict(statuses),
        total_duration_ms=round(total_duration_ms, 2),
        throughput_jobs_per_second=round(successful / (total_duration_ms / 1_000), 3),
        job_duration_p50_ms=round(statistics.median(durations), 2) if durations else 0,
        job_duration_p95_ms=round(percentile(durations, 0.95), 2) if durations else 0,
        uploaded_bytes=uploaded_bytes,
        passed=successful == len(resume_ids),
    )


def required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} in the process environment before running the baseline.")
    return value


async def run(args: argparse.Namespace) -> dict[str, Any]:
    origin = args.origin.rstrip("/")
    verify: bool | ssl.SSLContext = True
    if args.insecure_local_tls:
        verify = False
    elif args.ca_file:
        verify = ssl.create_default_context(cafile=args.ca_file)
    common = {
        "base_url": args.base_url.rstrip("/"),
        "headers": {"Origin": origin},
        "timeout": httpx.Timeout(args.timeout_seconds),
        "verify": verify,
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
            (student_client, "student_profile", "GET", "/profile", 750),
            (student_client, "resume_versions", "GET", "/resumes", 750),
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
            (
                admin_client,
                "admin_application_list",
                "GET",
                "/admin/recruitment/applications?page_size=50",
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
                    rounds=args.rounds,
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
                    rounds=1,
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
                    rounds=args.rounds,
                    concurrency=args.concurrency,
                    budget_p95_ms=1500,
                    headers=application_headers,
                    json_body=application_body,
                )
            )
            if args.expect_ai_degraded:
                scenarios.append(
                    await measure(
                        client=student_client,
                        name="semantic_match_provider_degraded",
                        method="POST",
                        path=f"/opportunities/{role_id}/match",
                        samples=min(args.samples, 5),
                        rounds=1,
                        concurrency=min(args.concurrency, 2),
                        budget_p95_ms=1500,
                        headers={"X-CSRF-Token": student_csrf},
                        expected_json={"status": "unavailable"},
                    )
                )
        else:
            skipped.append(
                {
                    "name": "idempotent_application_submission",
                    "reason": "PILOT_ROLE_ID and PILOT_RESUME_VERSION_ID were not supplied.",
                }
            )

        worker_result = None
        if args.resume_processing_samples:
            worker_result = await measure_worker_throughput(
                client=student_client,
                csrf_token=student_csrf,
                samples=args.resume_processing_samples,
                timeout_seconds=args.resume_processing_timeout_seconds,
            )

    return {
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment_label": args.environment_label,
        "base_url": args.base_url,
        "samples_per_scenario": args.samples,
        "rounds": args.rounds,
        "concurrency": args.concurrency,
        "budgets": "provisional pre-pilot engineering gates; institutional SLO approval pending",
        "scenarios": [asdict(item) for item in scenarios],
        "worker_throughput": asdict(worker_result) if worker_result else None,
        "resource_observations": {
            "database_pool_pressure": "captured by the performance rehearsal wrapper",
            "cpu_and_memory": "captured by the performance rehearsal wrapper",
            "provider_duration_and_cost": "no paid provider invoked when degraded mode is selected",
        },
        "skipped": skipped,
        "passed": all(item.passed for item in scenarios)
        and (worker_result is None or worker_result.passed),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure repeatable CampusHire pilot HTTP baselines."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--origin", default="http://127.0.0.1:3000")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--ca-file")
    parser.add_argument("--insecure-local-tls", action="store_true")
    parser.add_argument("--expect-ai-degraded", action="store_true")
    parser.add_argument("--resume-processing-samples", type=int, default=0)
    parser.add_argument("--resume-processing-timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--environment-label",
        default="local-development-not-production-capacity",
    )
    parser.add_argument("--output", default=".data/pilot-http-baseline.json")
    args = parser.parse_args()
    if args.samples < 5 or args.rounds < 1 or args.concurrency < 1:
        parser.error("Use at least 5 samples and concurrency of 1 or greater.")
    if args.resume_processing_samples < 0 or args.resume_processing_samples > 20:
        parser.error("--resume-processing-samples must be between 0 and 20.")
    if args.insecure_local_tls and not args.environment_label.startswith("local-"):
        parser.error("--insecure-local-tls requires an environment label beginning with 'local-'.")
    if args.insecure_local_tls and args.ca_file:
        parser.error("Use either --ca-file or --insecure-local-tls, not both.")
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
