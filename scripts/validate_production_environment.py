from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from scripts.validate_oci_environment import IMAGE_REFERENCE, IMAGE_VARIABLES, parse_environment

REQUIRED = (
    "PRODUCTION_HOST",
    "FRONTEND_ORIGINS",
    "TRUSTED_HOSTS",
    *IMAGE_VARIABLES,
    "OCI_OBJECT_NAMESPACE",
    "OCI_OBJECT_BUCKET",
    "OCI_OBJECT_QUOTA_BYTES",
    "OCI_OBJECT_UPLOADS_ENABLED",
    "PRODUCTION_SECRET_DIR",
    "PARSER_DOCKER_HOST",
    "PARSER_CLIENT_CERT_DIR",
    "DATABASE_URL",
    "REDIS_URL",
    "BACKUP_AGE_RECIPIENT",
    "EMAIL_SMTP_HOST",
    "EMAIL_SMTP_USERNAME",
    "EMAIL_SMTP_PASSWORD",
    "EMAIL_FROM_ADDRESS",
    "EMAIL_DELIVERY_WEBHOOK_KEY",
    "OPERATOR_BOOTSTRAP_KEY",
    "MFA_ENCRYPTION_KEY",
)


def validate_production_environment(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    missing = [name for name in REQUIRED if not values.get(name)]
    if missing:
        errors.append(f"missing required variables: {', '.join(missing)}")
    host = values.get("PRODUCTION_HOST", "")
    if host:
        parsed = urlparse(f"//{host}")
        if parsed.hostname != host or "/" in host or ":" in host:
            errors.append("PRODUCTION_HOST must be a hostname only")
        if host.endswith((".sslip.io", ".nip.io", ".example.com", ".example.org")):
            errors.append("PRODUCTION_HOST must be a real owned domain")
    for variable, expected in (
        ("FRONTEND_ORIGINS", [f"https://{host}"]),
        ("TRUSTED_HOSTS", [host]),
    ):
        try:
            value = json.loads(values.get(variable, ""))
        except json.JSONDecodeError:
            errors.append(f"{variable} must be valid JSON")
        else:
            if value != expected:
                errors.append(f"{variable} must contain only the production host")
    for variable in IMAGE_VARIABLES:
        value = values.get(variable, "")
        if value and not IMAGE_REFERENCE.fullmatch(value):
            errors.append(f"{variable} must be an immutable GHCR digest")
    parser_host = values.get("PARSER_DOCKER_HOST", "")
    if parser_host and parser_host != "tcp://host.docker.internal:2376":
        errors.append(
            "PARSER_DOCKER_HOST must use the authenticated same-VM rootless launcher endpoint"
        )
    for variable in ("PRODUCTION_SECRET_DIR", "PARSER_CLIENT_CERT_DIR"):
        value = values.get(variable, "")
        if value and not PurePosixPath(value).is_absolute():
            errors.append(f"{variable} must be an absolute path outside the repository")
    database_url = values.get("DATABASE_URL", "")
    if database_url and not database_url.startswith("postgresql+asyncpg://"):
        errors.append("DATABASE_URL must use postgresql+asyncpg")
    redis_url = values.get("REDIS_URL", "")
    if redis_url and not redis_url.startswith("redis://:"):
        errors.append("REDIS_URL must include an authenticated Redis connection")
    for variable in (
        "EMAIL_SMTP_PASSWORD",
        "EMAIL_DELIVERY_WEBHOOK_KEY",
        "OPERATOR_BOOTSTRAP_KEY",
        "MFA_ENCRYPTION_KEY",
    ):
        value = values.get(variable, "")
        if value and len(value) < 32:
            errors.append(f"{variable} must contain at least 32 characters")
    smtp_host = values.get("EMAIL_SMTP_HOST", "")
    if smtp_host and not re.fullmatch(
        r"smtp\.email\.[a-z0-9-]+\.oci\.oraclecloud\.com", smtp_host
    ):
        errors.append("EMAIL_SMTP_HOST must be a regional OCI Email Delivery endpoint")
    quota = values.get("OCI_OBJECT_QUOTA_BYTES", "")
    if not quota.isdigit() or not 1_000_000_000 <= int(quota) <= 14_000_000_000:
        errors.append("OCI_OBJECT_QUOTA_BYTES must be between 1 GB and the 14 GB guard")
    if values.get("OCI_OBJECT_UPLOADS_ENABLED", "").casefold() not in {"true", "false"}:
        errors.append("OCI_OBJECT_UPLOADS_ENABLED must be true or false")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate production without printing secrets")
    parser.add_argument("environment", type=Path)
    args = parser.parse_args()
    try:
        values = parse_environment(args.environment)
    except (OSError, UnicodeError, ValueError) as error:
        raise SystemExit(f"Production environment validation failed: {error}") from error
    errors = validate_production_environment(values)
    if errors:
        raise SystemExit("Production environment validation failed:\n- " + "\n- ".join(errors))
    print("Production environment validation passed")


if __name__ == "__main__":
    main()
