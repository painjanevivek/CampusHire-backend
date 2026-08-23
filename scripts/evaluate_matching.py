import argparse
import json
from pathlib import Path
from typing import Any

from app.modules.matching.scoring import score_match

DEFAULT_DATASET = Path("tests/fixtures/semantic-match-evaluation-v1.json")


def evaluate_dataset(path: Path) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    results: list[dict[str, object]] = []
    for case in dataset["cases"]:
        result = score_match(
            case["resume_vector"],
            case["role_vector"],
            set(case["student_skills"]),
            set(case["required_skills"]),
            case["project_evidence"],
        )
        passed = case["minimum_score"] <= result.score <= case["maximum_score"]
        results.append(
            {
                "id": case["id"],
                "score": result.score,
                "passed": passed,
                "scoring_version": result.version,
            }
        )
    passed_count = sum(1 for item in results if item["passed"])
    return {
        "dataset_version": dataset["dataset_version"],
        "scoring_version": dataset["scoring_version"],
        "case_count": len(results),
        "passed_count": passed_count,
        "pass_rate": passed_count / len(results) if results else 0,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate semantic match scoring fixtures")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    args = parser.parse_args()
    report = evaluate_dataset(args.dataset)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["pass_rate"] != 1:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
