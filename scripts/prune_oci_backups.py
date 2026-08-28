from __future__ import annotations

import argparse
import json
import shutil
import subprocess


def _oci_executable() -> str:
    executable = shutil.which("oci")
    if executable is None:  # pragma: no cover - production host dependency
        raise RuntimeError("OCI CLI is required")
    return executable


OCI_EXECUTABLE = _oci_executable()


def object_names(namespace: str, bucket: str, prefix: str) -> list[str]:
    result = subprocess.run(  # noqa: S603 - fixed executable and explicit arguments
        [
            OCI_EXECUTABLE, "os", "object", "list", "--namespace-name", namespace,
            "--bucket-name", bucket, "--prefix", prefix, "--all", "--output", "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    return sorted(item["name"] for item in payload["data"] if item["name"].endswith(".age"))


def prune(namespace: str, bucket: str, prefix: str, keep: int) -> list[str]:
    removed: list[str] = []
    for name in object_names(namespace, bucket, prefix)[:-keep]:
        for target in (name, f"{name}.sha256"):
            subprocess.run(  # noqa: S603 - fixed executable and provider object name
                [
                    OCI_EXECUTABLE, "os", "object", "delete", "--namespace-name", namespace,
                    "--bucket-name", bucket, "--object-name", target, "--force",
                ],
                check=True,
                capture_output=True,
            )
        removed.append(name)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce bounded encrypted backup retention")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--bucket", required=True)
    args = parser.parse_args()
    removed = prune(args.namespace, args.bucket, "backups/daily/", 7)
    removed += prune(args.namespace, args.bucket, "backups/weekly/", 4)
    print(json.dumps({"removed_recovery_points": len(removed)}))


if __name__ == "__main__":
    main()
