from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(".github/release/pilot-compatibility-manifest.json")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_IMAGES = {
    "frontend": "frontend",
    "api": "backend",
    "worker": "backend",
    "parser": "backend",
    "clamav": "backend",
}
EXPECTED_REPOSITORIES = {
    "frontend": "https://github.com/painjanevivek/CampusHire",
    "backend": "https://github.com/painjanevivek/CampusHire-backend",
}
EXPECTED_EXTERNAL_GATES = {
    "authorized_go_no_go",
    "governance_signoff",
    "registry_promotion",
    "representative_uat",
    "signature_and_provenance",
}


class ManifestError(ValueError):
    pass


def require_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ManifestError(f"{context} keys differ; missing={missing}, extra={extra}")


def parse_timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ManifestError(f"{context} must be an RFC 3339 UTC timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ManifestError(f"{context} must be an RFC 3339 UTC timestamp") from error


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_git(repository: Path, arguments: Sequence[str]) -> str:
    git = shutil.which("git")
    if git is None:
        raise ManifestError("git is required for compatibility validation")
    result = subprocess.run(  # noqa: S603 - executable is resolved; arguments are constrained.
        [git, *arguments],
        cwd=repository,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ManifestError(f"git {' '.join(arguments)} failed in {repository}: {detail}")
    return result.stdout.strip()


def migration_heads(versions_directory: Path) -> set[str]:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted(versions_directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values: dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if targets:
                    for target in targets:
                        if target in {"revision", "down_revision"}:
                            values[target] = ast.literal_eval(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in {"revision", "down_revision"} and node.value is not None:
                    values[node.target.id] = ast.literal_eval(node.value)
        revision = values.get("revision")
        down_revision = values.get("down_revision")
        if not isinstance(revision, str):
            raise ManifestError(f"{path} does not declare a string revision")
        revisions.add(revision)
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, (list, tuple)):
            parents.update(str(parent) for parent in down_revision)
        elif down_revision is not None:
            raise ManifestError(f"{path} has an unsupported down_revision")
    heads = revisions - parents
    if not heads:
        raise ManifestError("no Alembic migration head was discovered")
    return heads


def validate_structure(manifest: Mapping[str, Any]) -> None:
    require_keys(
        manifest,
        {
            "schema_version",
            "candidate_id",
            "classification",
            "decision",
            "repositories",
            "contract",
            "database",
            "images",
            "evidence",
            "external_gates",
        },
        "manifest",
    )
    if manifest["schema_version"] != 1:
        raise ManifestError("schema_version must be 1")
    if manifest["classification"] != "verified_local_pilot_candidate":
        raise ManifestError("classification must preserve the local-evidence boundary")
    if manifest["decision"] != "NO_GO_REAL_DATA":
        raise ManifestError("the candidate must not imply real-data release authorization")

    repositories = manifest["repositories"]
    if not isinstance(repositories, Mapping):
        raise ManifestError("repositories must be an object")
    require_keys(repositories, {"frontend", "backend"}, "repositories")
    for name, repository in repositories.items():
        require_keys(
            repository,
            {
                "repository",
                "phase",
                "commit_sha",
                "committed_at",
                "post_candidate_control_paths",
            },
            f"repositories.{name}",
        )
        if not GIT_SHA.fullmatch(repository["commit_sha"]):
            raise ManifestError(f"repositories.{name}.commit_sha must be a full Git SHA")
        if repository["repository"] != EXPECTED_REPOSITORIES[name]:
            raise ManifestError(f"repositories.{name}.repository is unexpected")
        try:
            datetime.fromisoformat(repository["committed_at"])
        except (TypeError, ValueError) as error:
            raise ManifestError(
                f"repositories.{name}.committed_at must be an RFC 3339 timestamp"
            ) from error
        if repository["phase"] != ("phase-08" if name == "frontend" else "phase-09"):
            raise ManifestError(f"repositories.{name}.phase is not the requested phase")
        if not isinstance(repository["post_candidate_control_paths"], list):
            raise ManifestError(f"repositories.{name}.post_candidate_control_paths must be a list")

    contract = manifest["contract"]
    require_keys(
        contract,
        {"path", "sha256", "frontend_observed_at", "backend_observed_at"},
        "contract",
    )
    if contract["path"] != "openapi/campushire.openapi.json":
        raise ManifestError("contract.path must identify the authoritative OpenAPI snapshot")
    if not SHA256.fullmatch("sha256:" + contract["sha256"]):
        raise ManifestError("contract.sha256 must be 64 lowercase hexadecimal characters")
    parse_timestamp(contract["frontend_observed_at"], "contract.frontend_observed_at")
    parse_timestamp(contract["backend_observed_at"], "contract.backend_observed_at")

    database = manifest["database"]
    require_keys(database, {"migration_head", "observed_at"}, "database")
    if not isinstance(database["migration_head"], str) or not database["migration_head"]:
        raise ManifestError("database.migration_head must be non-empty")
    parse_timestamp(database["observed_at"], "database.observed_at")

    images = manifest["images"]
    require_keys(images, set(EXPECTED_IMAGES), "images")
    for name, source_repository in EXPECTED_IMAGES.items():
        image = images[name]
        require_keys(
            image,
            {
                "local_reference",
                "digest",
                "digest_kind",
                "platform",
                "source_repository",
                "source_commit_sha",
                "built_at",
                "registry_status",
                "build_parameters",
            },
            f"images.{name}",
        )
        if not SHA256.fullmatch(image["digest"]):
            raise ManifestError(f"images.{name}.digest must be a SHA-256 digest")
        if image["digest_kind"] != "local_docker_image_id":
            raise ManifestError(f"images.{name}.digest_kind must remain explicit")
        if image["platform"] != "linux/amd64":
            raise ManifestError(f"images.{name}.platform must be linux/amd64")
        if image["source_repository"] != source_repository:
            raise ManifestError(f"images.{name}.source_repository is inconsistent")
        expected_sha = repositories[source_repository]["commit_sha"]
        if image["source_commit_sha"] != expected_sha:
            raise ManifestError(f"images.{name}.source_commit_sha is inconsistent")
        if image["registry_status"] != "not_published":
            raise ManifestError(f"images.{name} must not claim registry promotion")
        if not isinstance(image["build_parameters"], Mapping):
            raise ManifestError(f"images.{name}.build_parameters must be an object")
        if image["build_parameters"].get("oci_revision_label") != expected_sha:
            raise ManifestError(f"images.{name} does not bind its OCI revision label")
        parse_timestamp(image["built_at"], f"images.{name}.built_at")

    evidence = manifest["evidence"]
    require_keys(evidence, {"recorded_at", "verified_by", "verification_scope"}, "evidence")
    parse_timestamp(evidence["recorded_at"], "evidence.recorded_at")
    if evidence["verified_by"] != "local_automated_verification":
        raise ManifestError("evidence.verified_by must not imply an external approver")
    if not isinstance(evidence["verification_scope"], list) or not evidence["verification_scope"]:
        raise ManifestError("evidence.verification_scope must be a non-empty list")

    gates = manifest["external_gates"]
    require_keys(gates, EXPECTED_EXTERNAL_GATES, "external_gates")
    for gate, state in gates.items():
        require_keys(state, {"status", "evidence"}, f"external_gates.{gate}")
        if state != {"status": "pending", "evidence": None}:
            raise ManifestError(f"external_gates.{gate} must remain pending without evidence")


def validate_repository(name: str, root: Path, repository: Mapping[str, Any]) -> None:
    commit = repository["commit_sha"]
    run_git(root, ["cat-file", "-e", f"{commit}^{{commit}}"])
    run_git(root, ["merge-base", "--is-ancestor", commit, "HEAD"])
    subject = run_git(root, ["show", "-s", "--format=%s", commit])
    if repository["phase"] not in subject:
        raise ManifestError(f"{name} candidate commit subject does not identify its phase")
    committed_at = run_git(root, ["show", "-s", "--format=%cI", commit])
    if committed_at != repository["committed_at"]:
        raise ManifestError(f"{name} candidate commit timestamp differs from the manifest")
    changed = set(run_git(root, ["diff", "--name-only", f"{commit}..HEAD"]).splitlines())
    allowed = set(repository["post_candidate_control_paths"])
    if not changed <= allowed:
        unexpected = sorted(changed - allowed)
        raise ManifestError(f"{name} has post-candidate product changes: {unexpected}")


def validate_manifest(
    manifest_path: Path,
    frontend_root: Path,
    backend_root: Path,
    *,
    verify_local_images: bool = False,
) -> Mapping[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, Mapping):
        raise ManifestError("manifest root must be an object")
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    expected_manifest_hash = manifest_path.with_suffix(".sha256").read_text().strip()
    if sha256_bytes(canonical) != expected_manifest_hash:
        raise ManifestError("canonical manifest SHA-256 does not match its immutable lock")
    validate_structure(manifest)
    roots = {"frontend": frontend_root.resolve(), "backend": backend_root.resolve()}
    for name, root in roots.items():
        validate_repository(name, root, manifest["repositories"][name])

    contract_path = manifest["contract"]["path"]
    expected_contract = manifest["contract"]["sha256"]
    observed_contracts: dict[str, bytes] = {}
    for name, root in roots.items():
        current = (root / contract_path).read_bytes()
        commit = manifest["repositories"][name]["commit_sha"]
        committed = subprocess.run(  # noqa: S603 - executable and ref are validated.
            [shutil.which("git") or "git", "show", f"{commit}:{contract_path}"],
            cwd=root,
            capture_output=True,
            check=True,
        ).stdout
        normalized_current = current.replace(b"\r\n", b"\n")
        if normalized_current != committed or sha256_bytes(committed) != expected_contract:
            raise ManifestError(f"{name} OpenAPI snapshot does not match the bound candidate")
        observed_contracts[name] = current
    if observed_contracts["frontend"] != observed_contracts["backend"]:
        raise ManifestError("frontend and backend OpenAPI snapshots differ")

    heads = migration_heads(backend_root / "migrations" / "versions")
    if heads != {manifest["database"]["migration_head"]}:
        raise ManifestError(f"migration heads differ from manifest: {sorted(heads)}")

    if verify_local_images:
        docker = shutil.which("docker")
        if docker is None:
            raise ManifestError("docker is required for local image verification")
        for name, image in manifest["images"].items():
            result = subprocess.run(  # noqa: S603 - executable and reference are validated.
                [
                    docker,
                    "image",
                    "inspect",
                    image["local_reference"],
                    "--format",
                    '{{.Id}}|{{index .Config.Labels "org.opencontainers.image.revision"}}',
                ],
                capture_output=True,
                check=False,
                text=True,
            )
            expected = f"{image['digest']}|{image['source_commit_sha']}"
            if result.returncode != 0 or result.stdout.strip() != expected:
                raise ManifestError(f"local image digest mismatch for {name}")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the immutable pilot compatibility manifest"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--frontend", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--verify-local-images", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = validate_manifest(
        args.manifest,
        args.frontend,
        args.backend,
        verify_local_images=args.verify_local_images,
    )
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    print(f"verified {manifest['candidate_id']} manifest_sha256={sha256_bytes(canonical)}")


if __name__ == "__main__":
    main()
