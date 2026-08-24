from __future__ import annotations

from scripts.validate_shared_vm_environment import validate_shared_vm_environment
from tests.test_validate_oci_environment import valid_environment


def test_shared_vm_environment_accepts_a_dedicated_gateway_network() -> None:
    environment = valid_environment()
    environment["SHARED_GATEWAY_NETWORK"] = "vm-deploy_default"

    assert validate_shared_vm_environment(environment) == []


def test_shared_vm_environment_requires_a_safe_dedicated_network() -> None:
    environment = valid_environment()

    assert validate_shared_vm_environment(environment) == [
        "missing required variables: SHARED_GATEWAY_NETWORK"
    ]

    environment["SHARED_GATEWAY_NETWORK"] = "bridge"
    assert validate_shared_vm_environment(environment) == [
        "SHARED_GATEWAY_NETWORK must be a dedicated user-defined network"
    ]

    environment["SHARED_GATEWAY_NETWORK"] = "bad network"
    assert validate_shared_vm_environment(environment) == [
        "SHARED_GATEWAY_NETWORK must be a valid Docker network name"
    ]
