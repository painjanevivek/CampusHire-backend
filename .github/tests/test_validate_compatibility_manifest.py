from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

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

    def test_image_must_bind_the_source_repository_commit(self) -> None:
        manifest = copy.deepcopy(self.manifest())
        manifest["images"]["api"]["source_commit_sha"] = "0" * 40
        with self.assertRaisesRegex(VALIDATOR.ManifestError, "source_commit_sha"):
            VALIDATOR.validate_structure(manifest)


if __name__ == "__main__":
    unittest.main()
