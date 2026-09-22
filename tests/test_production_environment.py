from scripts.validate_production_environment import validate_production_environment


def valid_environment() -> dict[str, str]:
    digest = "ghcr.io/campushire/component@sha256:" + "a" * 64
    return {
        "PRODUCTION_HOST": "campushire.example.in",
        "FRONTEND_ORIGINS": '["https://campushire.example.in"]',
        "TRUSTED_HOSTS": '["campushire.example.in"]',
        "BACKEND_API_IMAGE": digest,
        "BACKEND_WORKER_IMAGE": digest,
        "FRONTEND_IMAGE": digest,
        "RESUME_PARSER_IMAGE": digest,
        "CLAMAV_IMAGE": digest,
        "OCI_OBJECT_NAMESPACE": "tenantnamespace",
        "OCI_OBJECT_BUCKET": "campushire-private-production",
        "OCI_BACKUP_BUCKET": "campushire-recovery-production",
        "RESTORE_REHEARSAL_BUCKET": "campushire-restore-rehearsal",
        "PRODUCTION_SECRET_DIR": "/opt/campushire/config/secrets",
        "PARSER_DOCKER_HOST": "tcp://host.docker.internal:2376",
        "PARSER_CLIENT_CERT_DIR": "/opt/campushire/config/parser-client-tls",
        "DATABASE_URL": "postgresql+asyncpg://campushire:secret@postgres:5432/campushire",
        "REDIS_URL": "redis://:secret@redis:6379/0",
        "BACKUP_AGE_RECIPIENT": "age1productionrecipient",
        "OPERATIONS_ALERT_WEBHOOK_URL": "https://alerts.example.in/campushire-hook",
        "OPERATIONS_ALERT_OWNER_REFERENCE": "on-call-primary",
        "BACKEND_GIT_SHA": "b" * 40,
        "FRONTEND_GIT_SHA": "f" * 40,
        "OPENAPI_SHA256": "c" * 64,
        "EMAIL_DELIVERY_MODE": "smtp",
        "EMAIL_SMTP_HOST": "smtp.email.ap-mumbai-1.oci.oraclecloud.com",
        "EMAIL_SMTP_USERNAME": "ocid1.user.oc1..smtp",
        "EMAIL_SMTP_PASSWORD": "s" * 32,
        "EMAIL_FROM_ADDRESS": "no-reply@campushire.example.in",
        "EMAIL_DELIVERY_WEBHOOK_KEY": "w" * 32,
        "OPERATOR_BOOTSTRAP_KEY": "o" * 32,
        "MFA_ENCRYPTION_KEY": "m" * 32,
        "OCI_OBJECT_QUOTA_BYTES": "14000000000",
        "OCI_OBJECT_UPLOADS_ENABLED": "true",
    }


def test_production_environment_accepts_owned_domain_and_immutable_images() -> None:
    assert validate_production_environment(valid_environment()) == []


def test_production_environment_blocks_staging_domain_and_mutable_image() -> None:
    values = valid_environment()
    values["PRODUCTION_HOST"] = "127-0-0-1.sslip.io"
    values["BACKEND_API_IMAGE"] = "ghcr.io/campushire/api:latest"
    errors = validate_production_environment(values)
    assert any("real owned domain" in error for error in errors)
    assert any("immutable" in error for error in errors)


def test_production_environment_requires_private_compose_dependencies() -> None:
    values = valid_environment()
    values.pop("PRODUCTION_SECRET_DIR")
    values["PARSER_DOCKER_HOST"] = "tcp://parser.example.in:2376"
    values["PARSER_CLIENT_CERT_DIR"] = "relative/certificates"
    values["DATABASE_URL"] = "postgres://campushire:secret@postgres/campushire"
    values["REDIS_URL"] = "redis://redis:6379/0"

    errors = validate_production_environment(values)

    assert any("PRODUCTION_SECRET_DIR" in error for error in errors)
    assert any("authenticated same-VM rootless launcher" in error for error in errors)
    assert any("absolute path outside the repository" in error for error in errors)
    assert any("postgresql+asyncpg" in error for error in errors)
    assert any("authenticated Redis connection" in error for error in errors)


def test_production_environment_enforces_bounded_oci_services() -> None:
    values = valid_environment()
    values["OCI_OBJECT_QUOTA_BYTES"] = "20000000000"
    values["EMAIL_SMTP_HOST"] = "smtp.example.in"
    values["EMAIL_SMTP_PASSWORD"] = "x" * 5

    errors = validate_production_environment(values)

    assert any("14 GB guard" in error for error in errors)
    assert any("OCI Email Delivery" in error for error in errors)
    assert any("EMAIL_SMTP_PASSWORD" in error for error in errors)


def test_production_environment_allows_explicit_approved_manual_handoff_without_smtp() -> None:
    values = valid_environment()
    values["EMAIL_DELIVERY_MODE"] = "manual"
    values["MANUAL_HANDOFF_APPROVAL_REFERENCE"] = "institution-signed-procedure-2026-09"
    for name in (
        "EMAIL_SMTP_HOST",
        "EMAIL_SMTP_USERNAME",
        "EMAIL_SMTP_PASSWORD",
        "EMAIL_DELIVERY_WEBHOOK_KEY",
    ):
        values.pop(name)
    assert validate_production_environment(values) == []

    values.pop("MANUAL_HANDOFF_APPROVAL_REFERENCE")
    assert any(
        "MANUAL_HANDOFF_APPROVAL_REFERENCE" in error
        for error in validate_production_environment(values)
    )


def test_production_environment_requires_separate_recovery_boundaries() -> None:
    values = valid_environment()
    values["OCI_BACKUP_BUCKET"] = values["OCI_OBJECT_BUCKET"]
    values["RESTORE_REHEARSAL_BUCKET"] = values["OCI_OBJECT_BUCKET"]

    errors = validate_production_environment(values)

    assert any("OCI_BACKUP_BUCKET must differ" in error for error in errors)
    assert any("RESTORE_REHEARSAL_BUCKET must differ" in error for error in errors)


def test_production_environment_requires_actionable_alert_and_candidate_identity() -> None:
    values = valid_environment()
    values["OPERATIONS_ALERT_WEBHOOK_URL"] = "http://localhost/hook"
    values["BACKEND_GIT_SHA"] = "short"
    values["OPENAPI_SHA256"] = "not-a-hash"

    errors = validate_production_environment(values)

    assert any("alert webhook" in error.casefold() for error in errors)
    assert any("BACKEND_GIT_SHA" in error for error in errors)
    assert any("OPENAPI_SHA256" in error for error in errors)
