from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.check_pilot_activation import (
    REQUIRED_NUMERIC_FIELDS,
    SCHEMA_VERSION,
    read_signing_key,
    sign_snapshot,
    validate_snapshot,
)


def build_snapshot(
    metrics: dict[str, Any],
    *,
    candidate_id: str,
    monitoring_source: str,
    authorization_reference: str,
    authorized_go: bool,
    signing_key: bytes,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": candidate_id,
        "generated_at_utc": (generated_at or datetime.now(UTC))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "monitoring_source": monitoring_source,
        "authorization_reference": authorization_reference,
        "authorized_go": authorized_go,
    }
    snapshot.update({field: metrics.get(field) for field in REQUIRED_NUMERIC_FIELDS})
    validate_snapshot(snapshot, now=generated_at)
    snapshot["signature"] = sign_snapshot(snapshot, signing_key)
    return snapshot


def write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a signed, fresh CampusHire pilot health snapshot."
    )
    parser.add_argument("metrics", type=Path, help="Approved monitoring export (metrics only)")
    parser.add_argument("output", type=Path)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--monitoring-source", required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--authorized-go", action="store_true")
    parser.add_argument("--hmac-key-file", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        if not isinstance(metrics, dict):
            raise ValueError("metrics export must be a JSON object")
        snapshot = build_snapshot(
            metrics,
            candidate_id=args.candidate_id,
            monitoring_source=args.monitoring_source,
            authorization_reference=args.authorization_reference,
            authorized_go=args.authorized_go,
            signing_key=read_signing_key(args.hmac_key_file),
        )
        write_private_json(args.output, snapshot)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Health snapshot build failed: {error}") from error
    print(f"Signed health snapshot written to {args.output}")


if __name__ == "__main__":
    main()
