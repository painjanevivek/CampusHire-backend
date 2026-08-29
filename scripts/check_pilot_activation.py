from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

Snapshot = Mapping[str, int | float | bool]

REQUIRED_FIELDS = {
    "authorized_go": bool,
    "consecutive_threshold_windows": int,
    "cpu_percent": (int, float),
    "memory_percent": (int, float),
    "disk_percent": (int, float),
    "object_allocation_percent": (int, float),
    "error_rate_percent": (int, float),
    "latency_budget_utilization_percent": (int, float),
    "backup_age_hours": (int, float),
    "certificate_days_remaining": (int, float),
    "database_pool_percent": (int, float),
    "worker_missed_lease_periods": int,
}


def validate_snapshot(value: object) -> Snapshot:
    if not isinstance(value, dict):
        raise ValueError("snapshot must be a JSON object")
    errors: list[str] = []
    for field, expected_type in REQUIRED_FIELDS.items():
        current = value.get(field)
        if current is None:
            errors.append(f"missing {field}")
        elif not isinstance(current, expected_type) or isinstance(current, bool) and expected_type is not bool:
            errors.append(f"{field} has an invalid type")
        elif isinstance(current, (int, float)) and current < 0:
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
