from pathlib import Path

from scripts.build_release_candidate_manifest import (
    RepositoryState,
    parse_gate_evidence,
    prohibited_tracked_paths,
    release_blockers,
    sha256_digest,
    sha256_file,
)
from scripts.hash_release_configuration import CONFIGURATION_PATHS, hash_release_configuration


def state(name: str, *, clean: bool = True, parity: bool = True) -> RepositoryState:
    return RepositoryState(
        name=name,
        branch="main",
        head="a" * 40,
        upstream="origin/main",
        remote_head="a" * 40,
        remote_parity=parity,
        clean=clean,
        dirty_paths=[] if clean else ["src/example.py"],
        prohibited_tracked_paths=[],
    )


def test_prohibited_release_paths_cover_local_guidance_and_generated_evidence() -> None:
    paths = ["AGENTS.md", ".agents/skills/local.txt", ".data/report.json", "app/main.py"]
    assert prohibited_tracked_paths(paths) == sorted(paths[:3])


def test_release_remains_no_go_until_every_artifact_and_gate_has_evidence() -> None:
    artifacts = {
        "frontend_image_digest": "sha256:front",
        "backend_image_digest": None,
    }
    blockers = release_blockers(
        [state("frontend"), state("backend", clean=False)],
        gate_evidence={"frontend_deep_scan": "report-1"},
        immutable_artifacts=artifacts,
    )
    assert "backend_worktree_not_clean" in blockers
    assert "immutable_artifact_pending:backend_image_digest" in blockers
    assert "external_gate_pending:backend_deep_scan" in blockers


def test_gate_evidence_and_hash_are_deterministic(tmp_path: Path) -> None:
    document = tmp_path / "contract.json"
    document.write_bytes(b"{}\n")
    assert parse_gate_evidence(["managed_staging=evidence/42"]) == {
        "managed_staging": "evidence/42"
    }
    assert sha256_file(document) == (
        "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"
    )
    assert sha256_digest("sha256:" + "A" * 64) == "sha256:" + "a" * 64


def test_release_configuration_hash_covers_both_deployables(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    for repository, relative_path in CONFIGURATION_PATHS:
        root = backend if repository == "backend" else frontend
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{repository}:{relative_path}\n", encoding="utf-8")

    first_hash, files = hash_release_configuration(backend, frontend)
    second_hash, _ = hash_release_configuration(backend, frontend)

    assert first_hash == second_hash
    assert len(files) == len(CONFIGURATION_PATHS)
    assert all(item.sha256 and item.bytes > 0 for item in files)

    (frontend / "Dockerfile").write_text("changed\n", encoding="utf-8")
    changed_hash, _ = hash_release_configuration(backend, frontend)
    assert changed_hash != first_hash
