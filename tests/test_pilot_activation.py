from datetime import UTC, datetime, timedelta

import pytest

from scripts.build_pilot_health_snapshot import build_snapshot
from scripts.check_pilot_activation import (
    activation_blockers,
    validate_snapshot,
    verify_snapshot_signature,
)

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
SIGNING_KEY = b"phase-nine-test-signing-key-32-bytes-minimum"


def healthy_snapshot() -> dict[str, object]:
    return {
        "schema_version": "1",
        "candidate_id": "frontend-fa02ff0_backend-4e43cc2",
        "generated_at_utc": NOW.isoformat().replace("+00:00", "Z"),
        "monitoring_source": "oci-production-monitoring-export",
        "authorization_reference": "release-authority/phase-09-test",
        "authorized_go": True,
        "consecutive_threshold_windows": 0,
        "cpu_percent": 42.0,
        "memory_percent": 54.0,
        "disk_percent": 41.0,
        "object_allocation_percent": 38.0,
        "error_rate_percent": 0.2,
        "latency_budget_utilization_percent": 45.0,
        "backup_age_hours": 3.0,
        "certificate_days_remaining": 90.0,
        "database_pool_percent": 38.0,
        "worker_missed_lease_periods": 0,
    }


def test_activation_allows_a_healthy_authorized_snapshot() -> None:
    snapshot = validate_snapshot(healthy_snapshot(), now=NOW)
    assert activation_blockers(snapshot) == []


def test_activation_pauses_after_persistent_capacity_pressure() -> None:
    snapshot = healthy_snapshot()
    snapshot["consecutive_threshold_windows"] = 3
    snapshot["cpu_percent"] = 70.0
    snapshot["latency_budget_utilization_percent"] = 80.0

    blockers = activation_blockers(snapshot)

    assert "cpu_capacity_threshold_persisted" in blockers
    assert "latency_budget_threshold_persisted" in blockers


def test_activation_blocks_immediate_operational_failures_and_missing_authorization() -> None:
    snapshot = healthy_snapshot()
    snapshot["authorized_go"] = False
    snapshot["backup_age_hours"] = 30.0
    snapshot["certificate_days_remaining"] = 14.0
    snapshot["database_pool_percent"] = 90.0
    snapshot["worker_missed_lease_periods"] = 2

    blockers = activation_blockers(snapshot)

    assert "authorized_go_missing" in blockers
    assert "backup_stale" in blockers
    assert "certificate_expiry_window" in blockers
    assert "database_pool_critical" in blockers
    assert "worker_heartbeat_missing" in blockers


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("cpu_percent", float("nan"), "must be finite"),
        ("memory_percent", float("inf"), "must be finite"),
        ("disk_percent", 101.0, "must not exceed 100"),
        ("consecutive_threshold_windows", 1.5, "must be an integer"),
    ],
)
def test_snapshot_rejects_malformed_or_unrealistic_metrics(
    field: str, value: float, message: str
) -> None:
    snapshot = healthy_snapshot()
    snapshot[field] = value
    with pytest.raises(ValueError, match=message):
        validate_snapshot(snapshot, now=NOW)


def test_snapshot_rejects_stale_and_future_timestamps() -> None:
    stale = healthy_snapshot()
    stale["generated_at_utc"] = (NOW - timedelta(minutes=11)).isoformat().replace(
        "+00:00", "Z"
    )
    with pytest.raises(ValueError, match="snapshot is stale"):
        validate_snapshot(stale, now=NOW)

    future = healthy_snapshot()
    future["generated_at_utc"] = (NOW + timedelta(minutes=2)).isoformat().replace(
        "+00:00", "Z"
    )
    with pytest.raises(ValueError, match="timestamp is in the future"):
        validate_snapshot(future, now=NOW)


def test_snapshot_builder_signs_the_exact_candidate_and_metrics() -> None:
    raw = healthy_snapshot()
    metrics = {
        key: value
        for key, value in raw.items()
        if key
        not in {
            "schema_version",
            "candidate_id",
            "generated_at_utc",
            "monitoring_source",
            "authorization_reference",
            "authorized_go",
        }
    }
    snapshot = build_snapshot(
        metrics,
        candidate_id=str(raw["candidate_id"]),
        monitoring_source=str(raw["monitoring_source"]),
        authorization_reference=str(raw["authorization_reference"]),
        authorized_go=True,
        signing_key=SIGNING_KEY,
        generated_at=NOW,
    )

    verify_snapshot_signature(snapshot, SIGNING_KEY)
    snapshot["cpu_percent"] = 43.0
    with pytest.raises(ValueError, match="signature is invalid"):
        verify_snapshot_signature(snapshot, SIGNING_KEY)
