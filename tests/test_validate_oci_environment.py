from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_oci_environment import parse_environment, validate_environment


def valid_environment() -> dict[str, str]:
    digest = "a" * 64
    host = "campushire-staging.duckdns.org"
    return {
        "STAGING_HOST": host,
        "FRONTEND_ORIGINS": f'["https://{host}"]',
        "TRUSTED_HOSTS": f'["{host}"]',
        "BACKEND_API_IMAGE": f"ghcr.io/painjanevivek/campushire-api@sha256:{digest}",
        "BACKEND_WORKER_IMAGE": (
            f"ghcr.io/painjanevivek/campushire-worker@sha256:{digest}"
        ),
        "FRONTEND_IMAGE": f"ghcr.io/painjanevivek/campushire-frontend@sha256:{digest}",
        "RESUME_PARSER_IMAGE": (
            f"ghcr.io/painjanevivek/campushire-parser@sha256:{digest}"
        ),
        "CLAMAV_IMAGE": f"ghcr.io/painjanevivek/campushire-clamav@sha256:{digest}",
        "PARSER_DOCKER_HOST": "tcp://host.docker.internal:2376",
        "PARSER_CLIENT_CERT_DIR": "/etc/campushire/parser-client-tls",
        "STAGING_SECRET_DIR": "/etc/campushire/secrets",
        "CADDYFILE_PATH": "../oci/Caddyfile",
        "DATABASE_URL": "postgresql+asyncpg://campushire:secret@postgres:5432/campushire",
        "REDIS_URL": "redis://:secret@redis:6379/0",
    }


def test_valid_environment_passes() -> None:
    assert validate_environment(valid_environment()) == []


def test_mutable_image_and_reserved_host_are_rejected() -> None:
    values = valid_environment()
    values["STAGING_HOST"] = "staging.example.org"
    values["FRONTEND_ORIGINS"] = '["https://staging.example.org"]'
    values["TRUSTED_HOSTS"] = '["staging.example.org"]'
    values["BACKEND_API_IMAGE"] = "ghcr.io/painjanevivek/campushire-api:latest"

    errors = validate_environment(values)

    assert any("reserved example domain" in error for error in errors)
    assert any("BACKEND_API_IMAGE" in error for error in errors)


def test_parser_launcher_must_use_same_vm_tls_endpoint() -> None:
    values = valid_environment()
    values["PARSER_DOCKER_HOST"] = "unix:///var/run/docker.sock"

    assert any("rootless launcher" in error for error in validate_environment(values))


def test_parser_rejects_duplicate_assignments_without_exposing_values(tmp_path: Path) -> None:
    environment = tmp_path / "staging.env"
    environment.write_text("STAGING_HOST=first\nSTAGING_HOST=second\n", encoding="utf-8")

    with pytest.raises(ValueError, match="repeats STAGING_HOST"):
        parse_environment(environment)
