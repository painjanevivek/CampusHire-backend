from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

PROHIBITED_TRACKED_PATHS = {
    "AGENTS.md",
    "CLAUDE.md",
    "design.md",
    "designs.md",
    "skills-lock.json",
}
PROHIBITED_TRACKED_PREFIXES = (".agents/", ".codebase-memory/", ".data/", "docs/visuals/")
REQUIRED_EXTERNAL_GATES = {
    "frontend_deep_scan",
    "backend_deep_scan",
    "managed_staging",
    "managed_recovery",
    "managed_capacity_and_cost",
    "representative_uat",
    "governance_signoff",
    "authorized_go_no_go",
}
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
REGISTRY_IMAGE_PATTERN = re.compile(
    r"^ghcr\.io/[a-z0-9_.-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}$"
)
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MIGRATION_HEAD_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


@dataclass(frozen=True)
class RepositoryState:
    name: str
    branch: str
    head: str
    upstream: str | None
    remote_head: str | None
    remote_parity: bool
    clean: bool
    dirty_paths: list[str]
    prohibited_tracked_paths: list[str]


def run_git(repository: Path, arguments: Sequence[str], *, optional: bool = False) -> str | None:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise RuntimeError("Git is required to build a release candidate manifest")
    result = subprocess.run(  # noqa: S603 - executable is resolved; arguments are internal constants.
        [git_executable, *arguments],
        cwd=repository,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.rstrip()
    if optional:
        return None
    message = result.stderr.strip() or result.stdout.strip() or "unknown git failure"
    raise RuntimeError(f"git {' '.join(arguments)} failed for {repository.name}: {message}")


def prohibited_tracked_paths(paths: Sequence[str]) -> list[str]:
    return sorted(
        path
        for path in paths
        if path in PROHIBITED_TRACKED_PATHS
        or any(path.startswith(prefix) for prefix in PROHIBITED_TRACKED_PREFIXES)
    )


def collect_repository(name: str, repository: Path) -> RepositoryState:
    resolved = repository.resolve(strict=True)
    if run_git(resolved, ["rev-parse", "--is-inside-work-tree"]) != "true":
        raise RuntimeError(f"{resolved} is not a Git worktree")
    head = run_git(resolved, ["rev-parse", "HEAD"])
    branch = run_git(resolved, ["branch", "--show-current"]) or "detached"
    upstream = run_git(resolved, ["rev-parse", "--abbrev-ref", "@{upstream}"], optional=True)
    remote_head = (
        run_git(resolved, ["rev-parse", "@{upstream}"], optional=True) if upstream else None
    )
    status = run_git(resolved, ["status", "--porcelain=v1", "--untracked-files=all"]) or ""
    dirty_paths = sorted(
        line[3:] if len(line) > 3 else line for line in status.splitlines() if line.strip()
    )
    tracked = (run_git(resolved, ["ls-files"]) or "").splitlines()
    return RepositoryState(
        name=name,
        branch=branch,
        head=head or "",
        upstream=upstream,
        remote_head=remote_head,
        remote_parity=bool(remote_head and head == remote_head),
        clean=not dirty_paths,
        dirty_paths=dirty_paths,
        prohibited_tracked_paths=prohibited_tracked_paths(tracked),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_gate_evidence(values: Sequence[str]) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for value in values:
        gate, separator, reference = value.partition("=")
        if not separator or gate not in REQUIRED_EXTERNAL_GATES or not reference.strip():
            allowed = ", ".join(sorted(REQUIRED_EXTERNAL_GATES))
            raise ValueError(f"Gate evidence must be NAME=REFERENCE; allowed names: {allowed}")
        evidence[gate] = reference.strip()
    return evidence


def sha256_digest(value: str) -> str:
    normalized = value.lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise argparse.ArgumentTypeError("expected sha256:<64 lowercase hexadecimal characters>")
    return normalized


def registry_image_reference(value: str) -> str:
    normalized = value.lower()
    if not REGISTRY_IMAGE_PATTERN.fullmatch(normalized):
        raise argparse.ArgumentTypeError(
            "expected a lowercase GHCR digest-pinned image reference"
        )
    return normalized


def git_sha(value: str) -> str:
    normalized = value.lower()
    if not GIT_SHA_PATTERN.fullmatch(normalized):
        raise argparse.ArgumentTypeError("expected a full 40-character Git SHA")
    return normalized


def migration_head(value: str) -> str:
    if not MIGRATION_HEAD_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "migration head may contain only letters, digits, and underscores"
        )
    return value


def release_blockers(
    repositories: Sequence[RepositoryState],
    *,
    gate_evidence: dict[str, str],
    immutable_artifacts: dict[str, str | None],
) -> list[str]:
    blockers: list[str] = []
    for repository in repositories:
        if not repository.clean:
            blockers.append(f"{repository.name}_worktree_not_clean")
        if not repository.remote_parity:
            blockers.append(f"{repository.name}_remote_parity_not_proven")
        if repository.prohibited_tracked_paths:
            blockers.append(f"{repository.name}_prohibited_files_tracked")
    blockers.extend(
        f"external_gate_pending:{gate}"
        for gate in sorted(REQUIRED_EXTERNAL_GATES - gate_evidence.keys())
    )
    blockers.extend(
        f"immutable_artifact_pending:{name}"
        for name, value in immutable_artifacts.items()
        if not value
    )
    return blockers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a sanitized CampusHire release manifest.")
    parser.add_argument("--frontend", type=Path, default=Path("../Frontend"))
    parser.add_argument("--backend", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path(".data/release-candidate.json"))
    parser.add_argument("--frontend-image-digest", type=sha256_digest)
    parser.add_argument("--frontend-image-reference", type=registry_image_reference)
    parser.add_argument("--backend-image-digest", type=sha256_digest)
    parser.add_argument("--backend-image-reference", type=registry_image_reference)
    parser.add_argument("--backend-worker-image-digest", type=sha256_digest)
    parser.add_argument("--backend-worker-image-reference", type=registry_image_reference)
    parser.add_argument("--parser-image-digest", type=sha256_digest)
    parser.add_argument("--parser-image-reference", type=registry_image_reference)
    parser.add_argument("--candidate-archive-sha256", type=sha256_digest)
    parser.add_argument("--rollback-archive-sha256", type=sha256_digest)
    parser.add_argument("--sbom-bundle-sha256", type=sha256_digest)
    parser.add_argument("--provenance-reference")
    parser.add_argument("--signature-reference")
    parser.add_argument("--migration-head", type=migration_head)
    parser.add_argument("--config-manifest-hash", type=sha256_digest)
    parser.add_argument("--rollback-frontend-sha", type=git_sha)
    parser.add_argument("--rollback-backend-sha", type=git_sha)
    parser.add_argument("--approved-gate", action="append", default=[])
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gate_evidence = parse_gate_evidence(args.approved_gate)
    repositories = [
        collect_repository("frontend", args.frontend),
        collect_repository("backend", args.backend),
    ]
    openapi_path = args.frontend / "openapi" / "campushire.openapi.json"
    image_pairs = (
        ("frontend", args.frontend_image_reference, args.frontend_image_digest),
        ("backend", args.backend_image_reference, args.backend_image_digest),
        ("backend_worker", args.backend_worker_image_reference, args.backend_worker_image_digest),
        ("parser", args.parser_image_reference, args.parser_image_digest),
    )
    for name, reference, digest in image_pairs:
        if reference and digest and not reference.endswith(f"@{digest}"):
            raise SystemExit(f"{name} image reference and digest must identify the same artifact")
    immutable_artifacts = {
        "frontend_image_digest": args.frontend_image_digest,
        "frontend_image_reference": args.frontend_image_reference,
        "backend_image_digest": args.backend_image_digest,
        "backend_image_reference": args.backend_image_reference,
        "backend_worker_image_digest": args.backend_worker_image_digest,
        "backend_worker_image_reference": args.backend_worker_image_reference,
        "parser_image_digest": args.parser_image_digest,
        "parser_image_reference": args.parser_image_reference,
        "candidate_archive_sha256": args.candidate_archive_sha256,
        "rollback_archive_sha256": args.rollback_archive_sha256,
        "sbom_bundle_sha256": args.sbom_bundle_sha256,
        "provenance_reference": args.provenance_reference,
        "signature_reference": args.signature_reference,
        "migration_head": args.migration_head,
        "config_manifest_hash": args.config_manifest_hash,
        "rollback_frontend_sha": args.rollback_frontend_sha,
        "rollback_backend_sha": args.rollback_backend_sha,
    }
    blockers = release_blockers(
        repositories,
        gate_evidence=gate_evidence,
        immutable_artifacts=immutable_artifacts,
    )
    payload = {
        "schema_version": 1,
        "recorded_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "decision": "NO_GO" if blockers else "READY_FOR_AUTHORIZED_GO_NO_GO",
        "repositories": [asdict(repository) for repository in repositories],
        "openapi_sha256": sha256_file(openapi_path),
        "immutable_artifacts": immutable_artifacts,
        "external_gate_evidence": gate_evidence,
        "blockers": blockers,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if args.strict and blockers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
