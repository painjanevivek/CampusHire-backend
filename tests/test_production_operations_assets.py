from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_backup_bundles_database_and_private_object_manifest() -> None:
    backup = read("deploy/production/backup.sh")
    restore = read("deploy/production/restore_rehearsal.sh")

    assert "database.dump object-manifest.json" in backup
    assert "--prefix quarantine/" in backup
    assert "--prefix clean/" in backup
    assert "oci os object head" in backup
    assert "item[\"name\"].endswith(\".age\")" in restore
    assert "Object manifest byte total does not match entries" in restore
    assert "postgres:17-alpine@sha256:" in restore


def test_operations_probe_covers_immediate_production_boundaries() -> None:
    probe = read("deploy/production/operations_check.sh")

    for expected in (
        "/api/v1/health/ready",
        "check_object_quota.sh",
        "disk_percent < 70",
        "certificate_days > 14",
        "backup_age_seconds < 108000",
        "records[2016:]",
        "postgres redis qdrant clamav api worker frontend gateway",
    ):
        assert expected in probe
    assert "resume" not in probe.casefold()


def test_privileged_installer_enables_both_bounded_timers() -> None:
    installer = read("deploy/production/install_host_units.sh")
    operations_timer = read(
        "deploy/production/systemd/campushire-operations-check.timer"
    )
    backup_timer = read("deploy/production/systemd/campushire-backup.timer")

    assert "EUID" in installer
    assert "campushire-backup.timer campushire-operations-check.timer" in installer
    assert "OnUnitActiveSec=5m" in operations_timer
    assert "OnCalendar=*-*-* 02:15:00 UTC" in backup_timer
