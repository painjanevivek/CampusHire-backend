from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.pool import NullPool

import app.worker as worker_module
from app.core.config import Settings
from app.core.database import database_engine_options


def production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "production",
        "process_role": "api",
        "frontend_origins": ["https://app.campushire.example"],
        "trusted_hosts": ["api.campushire.example"],
        "operator_bootstrap_key": "o" * 32,
        "mfa_encryption_key": "m" * 32,
        "resume_storage_backend": "oci",
        "oci_auth_mode": "api_key",
        "oci_object_namespace": "tenantnamespace",
        "oci_object_bucket": "campushire-private-production",
        "oci_tenancy_ocid": "ocid1.tenancy.oc1..example",
        "oci_user_ocid": "ocid1.user.oc1..example",
        "oci_key_fingerprint": "00:11:22:33",
        "oci_region": "ap-mumbai-1",
        "oci_private_key": "private-key-material",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_vercel_api_role_uses_external_pooler_without_local_worker_dependencies() -> None:
    settings = production_settings()

    assert settings.process_role == "api"
    assert database_engine_options(settings) == {"poolclass": NullPool}


def test_production_worker_still_requires_clamav_and_docker_parser() -> None:
    with pytest.raises(ValidationError, match="MALWARE_SCANNER=clamav"):
        production_settings(process_role="worker")

    with pytest.raises(ValidationError, match="RESUME_PARSER_BACKEND=docker"):
        production_settings(process_role="worker", malware_scanner="clamav")


def test_production_worker_accepts_hardened_processing_dependencies() -> None:
    settings = production_settings(
        process_role="worker",
        malware_scanner="clamav",
        resume_parser_backend="docker",
    )

    assert settings.process_role == "worker"
    assert database_engine_options(settings) == {"pool_pre_ping": True}


async def test_api_role_cannot_accidentally_start_the_durable_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: production_settings(process_role="api"),
    )

    with pytest.raises(RuntimeError, match="PROCESS_ROLE=api"):
        await worker_module.run_worker(once=True)


def test_production_api_rejects_blank_oci_api_key_material() -> None:
    with pytest.raises(ValidationError, match="OCI API key authentication"):
        production_settings(oci_private_key="")
