from pathlib import Path

import pytest

from app.modules.matching.scoring import qdrant_payload, score_match
from scripts.evaluate_matching import evaluate_dataset


def test_match_components_are_versioned_and_explainable() -> None:
    result = score_match([1.0, 0.0], [0.8, 0.2], {"Python", "SQL"}, {"python", "sql"}, 0.8)
    assert result.score >= 90
    assert result.skill_coverage == 1.0
    assert result.version == "match-v1"


def test_vector_dimensions_must_match() -> None:
    with pytest.raises(ValueError):
        score_match([1.0], [1.0, 0.0], set(), set(), 0)


def test_qdrant_metadata_always_carries_institution_boundary() -> None:
    payload = qdrant_payload("inst-1", "student-1", "resume-3", "gemini-embedding-001")
    assert payload["institution_id"] == "inst-1"
    assert payload["resume_version"] == "resume-3"


def test_reviewed_semantic_match_evaluation_dataset_passes() -> None:
    report = evaluate_dataset(Path("tests/fixtures/semantic-match-evaluation-v1.json"))
    assert report["dataset_version"] == "semantic-match-evaluation-v1"
    assert report["scoring_version"] == "match-v1"
    assert report["case_count"] == 4
    assert report["pass_rate"] == 1
