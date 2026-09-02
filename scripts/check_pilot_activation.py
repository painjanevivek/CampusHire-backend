from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

Snapshot = Mapping[str, Any]

SCHEMA_VERSION = "1"
MAX_SNAPSHOT_AGE = timedelta(minutes=10)
MAX_FUTURE_SKEW = timedelta(minutes=1)
SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9._:/@+-]{8,256}$")

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
PERCENT_FIELDS = (
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "object_allocation_percent",
    "error_rate_percent",
    "latency_budget_utilization_percent",
    "database_pool_percent",
)


def _parse_utc_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("generated_at_utc must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError("generated_at_utc must be a valid ISO-8601 timestamp") from error
    return parsed.astimezone(UTC)


def canonical_snapshot(snapshot: Snapshot) -> bytes:
    payload = {key: value for key, value in snapshot.items() if key != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_snapshot(snapshot: Snapshot, key: bytes) -> str:
    if len(key) < 32:
        raise ValueError("snapshot signing key must contain at least 32 bytes")
    return hmac.new(key, canonical_snapshot(snapshot), hashlib.sha256).hexdigest()


def verify_snapshot_signature(snapshot: Snapshot, key: bytes) -> None:
    signature = snapshot.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature):
        raise ValueError("snapshot signature is missing or malformed")
    if not hmac.compare_digest(signature, sign_snapshot(snapshot, key)):
        raise ValueError("snapshot signature is invalid")


def validate_snapshot(value: object, *, now: datetime | None = None) -> Snapshot:
    if not isinstance(value, dict):
        raise ValueError("snapshot must be a JSON object")
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    for field in ("candidate_id", "monitoring_source", "authorization_reference"):
        current = value.get(field)
        if not isinstance(current, str) or not SAFE_REFERENCE.fullmatch(current):
            errors.append(f"{field} is missing or malformed")
    authorized_go = value.get("authorized_go")
    if not isinstance(authorized_go, bool):
        errors.append("authorized_go must be a boolean")
    for field in REQUIRED_NUMERIC_FIELDS:
        current = value.get(field)
        if current is None:
            errors.append(f"missing {field}")
        elif isinstance(current, bool) or not isinstance(current, (int, float)):
            errors.append(f"{field} has an invalid type")
        elif not math.isfinite(float(current)):
            errors.append(f"{field} must be finite")
        elif current < 0:
            errors.append(f"{field} must not be negative")
    for field in PERCENT_FIELDS:
        current = value.get(field)
        if isinstance(current, (int, float)) and not isinstance(current, bool) and current > 100:
            errors.append(f"{field} must not exceed 100")
    for field in ("consecutive_threshold_windows", "worker_missed_lease_periods"):
        current = value.get(field)
        if isinstance(current, (int, float)) and not isinstance(current, bool):
            if not float(current).is_integer():
                errors.append(f"{field} must be an integer")
    try:
        generated_at = _parse_utc_timestamp(value.get("generated_at_utc"))
    except ValueError as error:
        errors.append(str(error))
    else:
        reference_time = (now or datetime.now(UTC)).astimezone(UTC)
        if generated_at > reference_time + MAX_FUTURE_SKEW:
            errors.append("snapshot timestamp is in the future")
        elif reference_time - generated_at > MAX_SNAPSHOT_AGE:
            errors.append("snapshot is stale")
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
    parser.add_argument(
        "--hmac-key-file",
        type=Path,
        required=True,
        help="Protected external file containing the activation-snapshot signing key",
    )
    return parser.parse_args()


def read_signing_key(path: Path) -> bytes:
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("snapshot signing key file must use mode 0600 or stricter")
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise ValueError("snapshot signing key must contain at least 32 bytes")
    return key


def main() -> None:
    args = parse_args()
    try:
        raw: Any = json.loads(args.snapshot.read_text(encoding="utf-8"))
        snapshot = validate_snapshot(raw)
        verify_snapshot_signature(snapshot, read_signing_key(args.hmac_key_file))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Pilot activation check failed: {error}") from error
    blockers = activation_blockers(snapshot)
    if blockers:
        print("PILOT_ONBOARDING_PAUSED: " + ",".join(blockers))
        raise SystemExit(2)
    print("PILOT_ONBOARDING_ALLOWED")


if __name__ == "__main__":
    main()
