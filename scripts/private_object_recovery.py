"""Create and verify encrypted-backup manifests for private object storage."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any


def _safe_object_path(root: Path, name: str) -> Path:
    key = PurePosixPath(name)
    if (
        key.is_absolute()
        or not key.parts
        or ".." in key.parts
        or key.parts[0] not in {"clean", "quarantine"}
    ):
        raise ValueError("Private object key is unsafe")
    resolved_root = root.resolve()
    local_path = resolved_root.joinpath(*key.parts).resolve()
    if resolved_root not in local_path.parents:
        raise ValueError("Private object key escapes the recovery directory")
    return local_path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_manifest(
    *, recorded_at: str, listing_paths: Iterable[Path], object_root: Path
) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    for listing_path in listing_paths:
        payload = json.loads(listing_path.read_text(encoding="utf-8"))
        for item in payload.get("data", []):
            name = str(item["name"])
            local_path = _safe_object_path(object_root, name)
            if not local_path.is_file():
                raise ValueError(f"Downloaded private object is missing: {name}")
            size = int(item["size"])
            if local_path.stat().st_size != size:
                raise ValueError(f"Downloaded private object size mismatch: {name}")
            objects.append(
                {
                    "name": name,
                    "size": size,
                    "etag": item.get("etag"),
                    "time_modified": item.get("time-modified"),
                    "sha256": _sha256(local_path),
                }
            )
    ordered = sorted(objects, key=lambda item: item["name"])
    return {
        "schema_version": 2,
        "recorded_at_utc": recorded_at,
        "object_count": len(ordered),
        "total_bytes": sum(item["size"] for item in ordered),
        "objects": ordered,
    }


def validate_manifest(manifest: dict[str, Any], object_root: Path) -> None:
    if manifest.get("schema_version") != 2:
        raise ValueError("Object manifest schema is unsupported")
    objects = manifest.get("objects")
    if not isinstance(objects, list):
        raise ValueError("Object manifest entries are missing")
    if manifest.get("object_count") != len(objects):
        raise ValueError("Object manifest count does not match entries")
    if manifest.get("total_bytes") != sum(int(item["size"]) for item in objects):
        raise ValueError("Object manifest byte total does not match entries")
    for item in objects:
        local_path = _safe_object_path(object_root, str(item.get("name", "")))
        if not local_path.is_file():
            raise ValueError("Object manifest file is missing")
        if local_path.stat().st_size != int(item["size"]):
            raise ValueError("Object size does not match manifest")
        if _sha256(local_path) != item.get("sha256"):
            raise ValueError("Object checksum does not match manifest")


def validate_uploaded_listing(
    manifest: dict[str, Any], *, restore_prefix: str, uploaded: dict[str, Any]
) -> None:
    prefix = restore_prefix.rstrip("/") + "/"
    actual = {
        (str(item["name"])[len(prefix) :], int(item["size"]))
        for item in uploaded.get("data", [])
        if str(item.get("name", "")).startswith(prefix)
    }
    expected = {
        (str(item["name"]), int(item["size"])) for item in manifest["objects"]
    }
    if actual != expected:
        raise ValueError("Rehearsal bucket contents do not match private-object backup")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Recovery JSON must be an object")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--recorded-at", required=True)
    create.add_argument("--listing", action="append", required=True, type=Path)
    create.add_argument("--object-root", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--manifest", required=True, type=Path)
    validate.add_argument("--object-root", required=True, type=Path)

    uploaded = subparsers.add_parser("validate-upload")
    uploaded.add_argument("--manifest", required=True, type=Path)
    uploaded.add_argument("--restore-prefix", required=True)
    uploaded.add_argument("--listing", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    if arguments.command == "create":
        manifest = create_manifest(
            recorded_at=arguments.recorded_at,
            listing_paths=arguments.listing,
            object_root=arguments.object_root,
        )
        arguments.output.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif arguments.command == "validate":
        validate_manifest(_load(arguments.manifest), arguments.object_root)
    else:
        validate_uploaded_listing(
            _load(arguments.manifest),
            restore_prefix=arguments.restore_prefix,
            uploaded=_load(arguments.listing),
        )


if __name__ == "__main__":
    main()
