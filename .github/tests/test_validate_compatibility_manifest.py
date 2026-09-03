from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "validate_compatibility_manifest.py"
SPEC = importlib.util.spec_from_file_location("compatibility_validator", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("could not load compatibility validator")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class CompatibilityManifestTests(unittest.TestCase):
    def manifest(self) -> dict[str, object]:
        path = ROOT / ".github" / "release" / "pilot-compatibility-manifest.json"
        return VALIDATOR.json.loads(path.read_text(encoding="utf-8"))

    def test_checked_manifest_has_complete_local_evidence(self) -> None:
        VALIDATOR.validate_structure(self.manifest())

    def test_external_gate_cannot_be_promoted_without_evidence(self) -> None:
        manifest = copy.deepcopy(self.manifest())
        manifest["external_gates"]["representative_uat"]["status"] = "approved"
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "must remain pending"):
            VALIDATOR.validate_structure(manifest)

    def test_historical_scan_cannot_promote_current_security_gate(self) -> None:
        manifest = copy.deepcopy(self.manifest())
        manifest["external_gates"]["affected_security_review"] = {
            "status": "approved",
            "evidence": "docs/PHASE10_SECURITY_CLOSURE_2026-08-28.md",
        }
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "must remain pending"):
            VALIDATOR.validate_structure(manifest)

    def test_machine_manifest_cannot_claim_image_evidence(self) -> None:
        manifest = copy.deepcopy(self.manifest())
        manifest["images"] = {"frontend": {"digest": "sha256:" + "0" * 64}}
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "keys differ"):
            VALIDATOR.validate_structure(manifest)

    def test_manifest_cannot_authorize_post_candidate_paths(self) -> None:
        manifest = copy.deepcopy(self.manifest())
        manifest["repositories"]["frontend"]["post_candidate_control_paths"] = [
            "src/app/page.tsx"
        ]
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "keys differ"):
            VALIDATOR.validate_structure(manifest)

    def test_verification_scope_is_validator_owned(self) -> None:
        manifest = copy.deepcopy(self.manifest())
        manifest["evidence"]["verification_scope"] = ["arbitrary smoke claim"]
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "validator policy"):
            VALIDATOR.validate_structure(manifest)

    def active_reference_text(self) -> tuple[str, str, str]:
        manifest_hash = (
            ROOT / ".github" / "release" / "pilot-compatibility-manifest.sha256"
        ).read_text(encoding="utf-8").strip()
        docs = next(
            path
            for path in (
                ROOT / "docs",
                ROOT.parent / "Backend" / "docs",
                ROOT / ".compat" / "backend" / "docs",
            )
            if (path / "CURRENT_RELEASE_STATUS.md").is_file()
        )
        status = (docs / "CURRENT_RELEASE_STATUS.md").read_text(encoding="utf-8")
        dossier = (docs / "REAL_DATA_PILOT_RELEASE_DOSSIER.md").read_text(
            encoding="utf-8"
        )
        return manifest_hash, status, dossier

    def test_active_status_and_dossier_are_bound_to_manifest(self) -> None:
        manifest_hash, status, dossier = self.active_reference_text()
        VALIDATOR.validate_active_evidence_references(
            self.manifest(), manifest_hash, status, dossier
        )

    def test_historical_security_closure_cannot_replace_active_reference(self) -> None:
        manifest_hash, status, dossier = self.active_reference_text()
        stale = status.replace(
            "Security qualification | Pending for this candidate",
            "Security qualification | Phase 10 security closure",
        )
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "active manifest/dossier"):
            VALIDATOR.validate_active_evidence_references(
                self.manifest(), manifest_hash, stale, dossier
            )

    def test_historical_conditional_approval_cannot_replace_active_reference(self) -> None:
        manifest_hash, status, dossier = self.active_reference_text()
        stale = dossier.replace(
            "Accountable approvals | Pending; candidate-specific controlled references required",
            "Accountable approvals | Approved with prerequisites on 2026-08-24",
        )
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "current candidate"):
            VALIDATOR.validate_active_evidence_references(
                self.manifest(), manifest_hash, status, stale
            )

    def test_validator_owned_policy_rejects_product_change(self) -> None:
        repository = self.manifest()["repositories"]["frontend"]
        outputs = [
            VALIDATOR.EXPECTED_REPOSITORIES["frontend"],
            "",
            "",
            "fix(phase-08): verified candidate",
            repository["committed_at"],
            "src/app/page.tsx",
        ]
        with mock.patch.object(VALIDATOR, "run_git", side_effect=outputs):
            with self.assertRaisesRegex(VALIDATOR.ManifestError, "product changes"):
                VALIDATOR.validate_repository("frontend", ROOT, repository)

    def test_repository_validation_rejects_dirty_worktree(self) -> None:
        repository = self.manifest()["repositories"]["frontend"]
        outputs = [
            VALIDATOR.EXPECTED_REPOSITORIES["frontend"],
            "",
            "",
            "fix(phase-08): verified candidate",
            repository["committed_at"],
            "",
            "?? src/app/untracked.tsx",
        ]
        with mock.patch.object(VALIDATOR, "run_git", side_effect=outputs):
            with self.assertRaisesRegex(VALIDATOR.ManifestError, "working tree must be clean"):
                VALIDATOR.validate_repository("frontend", ROOT, repository)


if __name__ == "__main__":
    unittest.main()
