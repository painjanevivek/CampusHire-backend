from pathlib import Path

from scripts.build_release_candidate_manifest import (
    RepositoryState,
    parse_gate_evidence,
    prohibited_tracked_paths,
    release_blockers,
    sha256_file,
)


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
