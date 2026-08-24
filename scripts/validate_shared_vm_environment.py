from __future__ import annotations

import argparse
import re
from pathlib import Path

from scripts.validate_oci_environment import parse_environment, validate_environment

NETWORK_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


def validate_shared_vm_environment(values: dict[str, str]) -> list[str]:
    errors = validate_environment(values)
    network = values.get("SHARED_GATEWAY_NETWORK", "")
    if not network:
        errors.append("missing required variables: SHARED_GATEWAY_NETWORK")
    elif not NETWORK_NAME.fullmatch(network):
        errors.append("SHARED_GATEWAY_NETWORK must be a valid Docker network name")
    elif network in {"bridge", "host", "none"}:
        errors.append("SHARED_GATEWAY_NETWORK must be a dedicated user-defined network")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a shared-VM staging environment without printing protected values."
    )
    parser.add_argument("environment", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        values = parse_environment(args.environment)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"Shared-VM environment validation failed: {exc}") from exc
    errors = validate_shared_vm_environment(values)
    if errors:
        raise SystemExit("Shared-VM environment validation failed:\n- " + "\n- ".join(errors))
    print("Shared-VM environment validation passed")


if __name__ == "__main__":
    main()
