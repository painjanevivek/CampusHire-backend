import json
from pathlib import Path

from app.modules.generative.schemas import EvidenceReference, GroundedClaim, ResumeDraft
from app.modules.generative.service import ProposalValidationError, validate_grounding

FIXTURE = Path(__file__).parents[1] / "tests" / "fixtures" / "generative-evaluation-v1.json"
REQUIRED_CATEGORIES = {
    "bias_academic_background",
    "citation_accuracy",
    "cost",
    "cross_institution_leakage",
    "groundedness",
    "latency",
    "prompt_injection",
    "provider_failure",
    "tool_authorization",
    "unsupported_claim",
}


def main() -> int:
    suite = json.loads(FIXTURE.read_text(encoding="utf-8"))
    failures: list[str] = []
    categories = {case["category"] for case in suite["cases"]}
    failures.extend(f"missing-category:{item}" for item in sorted(REQUIRED_CATEGORIES - categories))
    for blocker in ("cross_tenant_leakage", "unauthorized_state_changes"):
        if suite["release_blockers"].get(blocker) != 0:
            failures.append(f"release-blocker:{blocker}")
    for case in suite["cases"]:
        if "claim" not in case:
            continue
        reference = EvidenceReference(
            evidence_id=f"fixture:{case['id']}",
            kind="fixture",
            label=case["id"],
            facts=case["evidence"],
        )
        draft = ResumeDraft(
            project_bullets=[
                GroundedClaim(text=case["claim"], evidence_ids=[reference.evidence_id])
            ]
        )
        accepted = True
        try:
            validate_grounding(draft, [reference])
        except ProposalValidationError:
            accepted = False
        if accepted != (case["expected"] == "accepted"):
            failures.append(case["id"])
    print(json.dumps({"suite": suite["version"], "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
