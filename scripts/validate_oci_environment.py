from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

IMAGE_REFERENCE = re.compile(r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[a-f0-9]{64}$")
IMAGE_VARIABLES = (
    "BACKEND_API_IMAGE",
    "BACKEND_WORKER_IMAGE",
    "FRONTEND_IMAGE",
    "RESUME_PARSER_IMAGE",
    "CLAMAV_IMAGE",
)
REQUIRED_VARIABLES = (
    "STAGING_HOST",
    "FRONTEND_ORIGINS",
    "TRUSTED_HOSTS",
    *IMAGE_VARIABLES,
    "PARSER_DOCKER_HOST",
    "PARSER_CLIENT_CERT_DIR",
    "STAGING_SECRET_DIR",
    "CADDYFILE_PATH",
    "DATABASE_URL",
    "REDIS_URL",
)


def parse_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"line {line_number} is not a KEY=VALUE assignment")
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise ValueError(f"line {line_number} has an invalid variable name")
        if name in values:
            raise ValueError(f"line {line_number} repeats {name}")
        values[name] = value.strip()
    return values


def validate_environment(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    missing = [name for name in REQUIRED_VARIABLES if not values.get(name)]
    if missing:
        errors.append(f"missing required variables: {', '.join(missing)}")

    host = values.get("STAGING_HOST", "")
    if host:
        if urlparse(f"//{host}").hostname != host or "/" in host or ":" in host:
            errors.append("STAGING_HOST must be a hostname without a scheme, path, or port")
        if host.endswith((".example.com", ".example.org", ".example.edu")):
            errors.append("STAGING_HOST must not use a reserved example domain")

    expected_origin = f"https://{host}" if host else ""
    for variable in ("FRONTEND_ORIGINS", "TRUSTED_HOSTS"):
        raw_value = values.get(variable, "")
        if not raw_value:
            continue
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError:
            errors.append(f"{variable} must be valid JSON")
            continue
        if not isinstance(parsed_value, list) or not all(
            isinstance(item, str) for item in parsed_value
        ):
            errors.append(f"{variable} must be a JSON array of strings")
            continue
        expected_value = [expected_origin] if variable == "FRONTEND_ORIGINS" else [host]
        if parsed_value != expected_value:
            errors.append(f"{variable} must contain only the selected staging host")

    for variable in IMAGE_VARIABLES:
        value = values.get(variable, "")
        if value and not IMAGE_REFERENCE.fullmatch(value):
            errors.append(f"{variable} must be an immutable lowercase GHCR sha256 reference")

    parser_host = values.get("PARSER_DOCKER_HOST", "")
    if parser_host and parser_host != "tcp://host.docker.internal:2376":
        errors.append(
            "PARSER_DOCKER_HOST must use the authenticated same-VM rootless launcher endpoint"
        )

    for variable in ("PARSER_CLIENT_CERT_DIR", "STAGING_SECRET_DIR"):
        value = values.get(variable, "")
        if value and not PurePosixPath(value).is_absolute():
            errors.append(f"{variable} must be an absolute path outside the repository")

    database_url = values.get("DATABASE_URL", "")
    if database_url and not database_url.startswith("postgresql+asyncpg://"):
        errors.append("DATABASE_URL must use postgresql+asyncpg")
    redis_url = values.get("REDIS_URL", "")
    if redis_url and not redis_url.startswith("redis://:"):
        errors.append("REDIS_URL must include an authenticated Redis connection")

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate an OCI staging environment without printing protected values."
    )
    parser.add_argument("environment", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        values = parse_environment(args.environment)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"OCI environment validation failed: {exc}") from exc
    errors = validate_environment(values)
    if errors:
        raise SystemExit("OCI environment validation failed:\n- " + "\n- ".join(errors))
    print("OCI environment validation passed")


if __name__ == "__main__":
    main()
