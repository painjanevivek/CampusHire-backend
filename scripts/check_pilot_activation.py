from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

Snapshot = Mapping[str, int | float | bool]

REQUIRED_NUMERIC_FIELDS = (
    "consecutive_threshold_windows",
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "object_allocation_percent",
    "error_rate_percent",
    "latency_budget_utilization_percent",
    "backup_age_hours",
    "certificate_days_remaining",
    "database_pool_percent",
    "worker_missed_lease_periods",
)


def validate_snapshot(value: object) -> Snapshot:
    if not isinstance(value, dict):
        raise ValueError("snapshot must be a JSON object")
    errors: list[str] = []
    authorized_go = value.get("authorized_go")
    if not isinstance(authorized_go, bool):
        errors.append("authorized_go must be a boolean")
    for field in REQUIRED_NUMERIC_FIELDS:
        current = value.get(field)
        if current is None:
            errors.append(f"missing {field}")
        elif isinstance(current, bool) or not isinstance(current, (int, float)):
            errors.append(f"{field} has an invalid type")
        elif current < 0:
            errors.append(f"{field} must not be negative")
    if errors:
        raise ValueError("invalid snapshot: " + "; ".join(errors))
    return value


def activation_blockers(snapshot: Snapshot) -> list[str]:
    blockers: list[str] = []
    if not bool(snapshot["authorized_go"]):
        blockers.append("authorized_go_missing")
    if float(snapshot["backup_age_hours"]) >= 30:
        blockers.append("backup_stale")
    if float(snapshot["certificate_days_remaining"]) <= 14:
        blockers.append("certificate_expiry_window")
    if float(snapshot["database_pool_percent"]) >= 90:
        blockers.append("database_pool_critical")
    if int(snapshot["worker_missed_lease_periods"]) >= 2:
        blockers.append("worker_heartbeat_missing")
    if int(snapshot["consecutive_threshold_windows"]) >= 3:
        thresholds = (
            ("cpu_percent", 70, "cpu_capacity_threshold_persisted"),
            ("memory_percent", 75, "memory_capacity_threshold_persisted"),
            ("disk_percent", 70, "disk_capacity_threshold_persisted"),
            ("object_allocation_percent", 70, "object_capacity_threshold_persisted"),
            ("error_rate_percent", 1, "error_rate_threshold_persisted"),
            ("latency_budget_utilization_percent", 80, "latency_budget_threshold_persisted"),
        )
        blockers.extend(
            blocker
            for field, threshold, blocker in thresholds
            if float(snapshot[field]) >= threshold
        )
    return blockers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Allow or pause CampusHire pilot onboarding from a sanitized health snapshot."
    )
    parser.add_argument("snapshot", type=Path, help="Path to a sanitized JSON health snapshot")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        raw: Any = json.loads(args.snapshot.read_text(encoding="utf-8"))
        snapshot = validate_snapshot(raw)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Pilot activation check failed: {error}") from error
    blockers = activation_blockers(snapshot)
    if blockers:
        print("PILOT_ONBOARDING_PAUSED: " + ",".join(blockers))
        raise SystemExit(2)
    print("PILOT_ONBOARDING_ALLOWED")


if __name__ == "__main__":
    main()
