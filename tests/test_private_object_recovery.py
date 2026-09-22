from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.private_object_recovery import (
    create_manifest,
    validate_manifest,
    validate_uploaded_listing,
)


def write_listing(path: Path, *, name: str, content: bytes) -> None:
    path.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "name": name,
                        "size": len(content),
                        "etag": "fixture-etag",
                        "time-modified": "2026-09-23T00:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_manifest_round_trip_verifies_bytes_and_rehearsal_listing(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    private_file = object_root / "clean" / "institution" / "resume.pdf"
    private_file.parent.mkdir(parents=True)
    content = b"synthetic-private-object"
    private_file.write_bytes(content)
    listing = tmp_path / "clean.json"
    write_listing(listing, name="clean/institution/resume.pdf", content=content)

    manifest = create_manifest(
        recorded_at="2026-09-23T00:00:00Z",
        listing_paths=[listing],
        object_root=object_root,
    )

    assert manifest["object_count"] == 1
    assert manifest["total_bytes"] == len(content)
    assert manifest["objects"][0]["sha256"] == hashlib.sha256(content).hexdigest()
    validate_manifest(manifest, object_root)
    validate_uploaded_listing(
        manifest,
        restore_prefix="restore-rehearsal/run-1",
        uploaded={
            "data": [
                {
                    "name": "restore-rehearsal/run-1/clean/institution/resume.pdf",
                    "size": len(content),
                }
            ]
        },
    )


def test_manifest_rejects_traversal_and_tampered_bytes(tmp_path: Path) -> None:
    object_root = tmp_path / "objects"
    object_root.mkdir()
    listing = tmp_path / "unsafe.json"
    write_listing(listing, name="clean/../../secret", content=b"x")
    with pytest.raises(ValueError, match="unsafe"):
        create_manifest(
            recorded_at="2026-09-23T00:00:00Z",
            listing_paths=[listing],
            object_root=object_root,
        )

    private_file = object_root / "clean" / "resume.pdf"
    private_file.parent.mkdir()
    private_file.write_bytes(b"original")
    write_listing(listing, name="clean/resume.pdf", content=b"original")
    manifest = create_manifest(
        recorded_at="2026-09-23T00:00:00Z",
        listing_paths=[listing],
        object_root=object_root,
    )
    private_file.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        validate_manifest(manifest, object_root)


def test_upload_verification_rejects_missing_or_extra_objects() -> None:
    manifest = {
        "objects": [{"name": "clean/resume.pdf", "size": 8}],
    }
    with pytest.raises(ValueError, match="do not match"):
        validate_uploaded_listing(
            manifest,
            restore_prefix="restore-rehearsal/run-1",
            uploaded={"data": []},
        )
