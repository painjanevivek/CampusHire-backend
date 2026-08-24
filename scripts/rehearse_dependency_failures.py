from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DrillResult:
    name: str
    command: list[str]
    duration_ms: int
    passed: bool
    evidence_tail: str


def run_drill(
    name: str, command: list[str], *, environment: dict[str, str] | None = None
) -> DrillResult:
    started = time.perf_counter()
    process = subprocess.run(  # noqa: S603 - commands are fixed below
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    duration_ms = round((time.perf_counter() - started) * 1_000)
    output = "\n".join(part.strip() for part in (process.stdout, process.stderr) if part.strip())
    return DrillResult(
        name=name,
        command=command,
        duration_ms=duration_ms,
        passed=process.returncode == 0,
        evidence_tail=output[-1_000:],
    )


def pytest_drill(name: str, node_id: str) -> DrillResult:
    return run_drill(name, [sys.executable, "-m", "pytest", "-q", node_id])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rehearse bounded local dependency failures with synthetic fixtures"
    )
    parser.add_argument("--parser-image", default="campushire-pdf-parser:test")
    parser.add_argument("--output", default=".data/dependency-failure-rehearsal.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    unavailable_ai_environment = dict(os.environ)
    unavailable_ai_environment["GEMINI_API_KEY"] = ""
    unavailable_ai_environment["QDRANT_URL"] = "http://127.0.0.1:1"
    results = [
        pytest_drill(
            "redis_outage_fails_closed",
            "tests/test_hardening.py::test_expensive_operation_fails_closed_in_production_without_redis",
        ),
        pytest_drill(
            "worker_termination_and_stale_lease_recover",
            "tests/test_profile_resume_pipeline.py::test_resume_pipeline_requires_review_and_rejects_unsupported_claims",
        ),
        pytest_drill(
            "stale_exhausted_job_is_terminal",
            "tests/test_operations.py::test_stale_exhausted_job_becomes_inspectable_terminal_failure",
        ),
        pytest_drill(
            "application_replay_prevents_duplicate_business_effect",
            "tests/test_recruitment_operations.py::test_application_is_idempotent_and_preserves_immutable_decision_inputs",
        ),
        pytest_drill(
            "notification_retry_prevents_duplicate_delivery",
            "tests/test_notifications.py::test_retry_does_not_duplicate_notification",
        ),
        pytest_drill(
            "clamav_outage_retries_without_data_loss",
            "tests/test_profile_resume_pipeline.py::test_scanner_outage_retries_without_losing_the_authoritative_job",
        ),
        pytest_drill(
            "private_object_store_cleanup_retries",
            "tests/test_privacy.py::test_deletion_removes_authoritative_data_then_retries_private_cleanup",
        ),
        pytest_drill(
            "private_object_store_terminal_failure_is_safe",
            "tests/test_privacy.py::test_private_cleanup_records_a_safe_terminal_failure",
        ),
        pytest_drill(
            "gemini_outage_degrades_semantic_match",
            "tests/test_reviewed_intelligence.py::test_match_is_versioned_separate_and_degrades_without_provider",
        ),
        run_drill(
            "parser_timeout_and_cleanup",
            [
                sys.executable,
                "scripts/verify_parser_sandbox.py",
                "--image",
                args.parser_image,
            ],
        ),
        run_drill(
            "qdrant_and_gemini_absent_core_operations_continue",
            [sys.executable, "scripts/smoke_phases.py"],
            environment=unavailable_ai_environment,
        ),
    ]
    payload = {
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": "local-synthetic-controlled-failures",
        "results": [asdict(result) for result in results],
        "passed": all(result.passed for result in results),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
