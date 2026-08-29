from scripts.check_pilot_activation import activation_blockers


def healthy_snapshot() -> dict[str, int | float | bool]:
    return {
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
    assert activation_blockers(healthy_snapshot()) == []


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
