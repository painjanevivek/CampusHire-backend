from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_backup_bundles_database_and_checksum_verified_private_objects() -> None:
    backup = read("deploy/production/backup.sh")
    restore = read("deploy/production/restore_rehearsal.sh")
    recovery = read("scripts/private_object_recovery.py")

    assert "database.dump object-manifest.json private-objects" in backup
    assert "oci os object bulk-download" in backup
    assert "--prefix quarantine/" in backup
    assert "--prefix clean/" in backup
    assert "oci os object head" in backup
    assert 'backup_bucket="$(read_value OCI_BACKUP_BUCKET)"' in backup
    assert "item[\"name\"].endswith(\".age\")" in restore
    assert "Object manifest byte total does not match entries" in recovery
    assert "Object checksum does not match manifest" in recovery
    assert "oci os object bulk-upload" in restore
    assert 'rehearsal_bucket="$(read_value RESTORE_REHEARSAL_BUCKET)"' in restore
    assert "postgres:17-alpine@sha256:" in restore


def test_operations_probe_covers_immediate_production_boundaries() -> None:
    probe = read("deploy/production/operations_check.sh")

    for expected in (
        "/api/v1/health/ready",
        "check_object_quota.sh",
        "disk_percent < 70",
        "certificate_days > 14",
        "backup_age_seconds < 108000",
        "worker_oldest_queued_seconds < 600",
        "worker_expired_leases == 0",
        "records[2016:]",
        "postgres redis qdrant clamav api worker frontend gateway",
    ):
        assert expected in probe
    assert "resume_processing_jobs" in probe
    assert "agent_runs" in probe
    assert "data_deletion_requests" in probe


def test_privileged_installer_enables_bounded_timers_and_failure_alerts() -> None:
    installer = read("deploy/production/install_host_units.sh")
    backup_service = read("deploy/production/systemd/campushire-backup.service")
    operations_service = read(
        "deploy/production/systemd/campushire-operations-check.service"
    )
    alert_service = read("deploy/production/systemd/campushire-alert@.service")
    alert_script = read("deploy/production/send_failure_alert.sh")
    operations_timer = read(
        "deploy/production/systemd/campushire-operations-check.timer"
    )
    backup_timer = read("deploy/production/systemd/campushire-backup.timer")

    assert "EUID" in installer
    assert "campushire-backup.timer campushire-operations-check.timer" in installer
    assert "campushire-alert@.service" in installer
    assert "OnFailure=campushire-alert@%n.service" in backup_service
    assert "OnFailure=campushire-alert@%n.service" in operations_service
    assert "OPERATIONS_ALERT_WEBHOOK_URL" in alert_script
    assert "OPERATIONS_ALERT_OWNER_REFERENCE" in alert_script
    assert "%i" in alert_service
    assert "OnUnitActiveSec=5m" in operations_timer
    assert "OnCalendar=*-*-* 02:15:00 UTC" in backup_timer


def test_images_embed_candidate_traceability_labels() -> None:
    dockerfile = read("Dockerfile")
    deploy = read("deploy/production/deploy.sh")

    assert "org.opencontainers.image.revision" in dockerfile
    assert "com.campushire.openapi-sha256" in dockerfile
    assert "BACKEND_GIT_SHA" in deploy
    assert "FRONTEND_GIT_SHA" in deploy
    assert "OPENAPI_SHA256" in deploy
    assert "docker image inspect" in deploy
