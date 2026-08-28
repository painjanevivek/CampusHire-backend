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
        "BACKUP_AGE_RECIPIENT": "age1productionrecipient",
        "EMAIL_SMTP_HOST": "smtp.email.ap-mumbai-1.oci.oraclecloud.com",
        "EMAIL_SMTP_USERNAME": "ocid1.user.oc1..smtp",
        "EMAIL_SMTP_PASSWORD": "generated-secret",
        "EMAIL_FROM_ADDRESS": "no-reply@campushire.example.in",
        "EMAIL_DELIVERY_WEBHOOK_KEY": "w" * 32,
        "OPERATOR_BOOTSTRAP_KEY": "o" * 32,
        "MFA_ENCRYPTION_KEY": "m" * 32,
        "OCI_OBJECT_QUOTA_BYTES": "14000000000",
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
