import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MatchResult:
    score: int
    semantic: float
    skill_coverage: float
    project_evidence: float
    version: str


def profile_compatibility(
    *, student_skills: set[str], resume_skills: set[str],
    target_roles: list[str], role_skills: list[str], role_title: str,
) -> int | None:
    """A bounded, explainable dashboard estimate; never an eligibility decision."""
    required = {skill.strip().casefold() for skill in role_skills if skill.strip()}
    if not required:
        return None
    evidence = {
        skill.strip().casefold()
        for skill in student_skills | resume_skills
        if skill.strip()
    }
    skill_coverage = len(required & evidence) / len(required)
    title_tokens = set(re.findall(r"[a-z0-9]+", role_title.casefold()))
    target_overlap = max(
        (
            len(title_tokens & set(re.findall(r"[a-z0-9]+", target.casefold())))
            / len(title_tokens)
            for target in target_roles
            if title_tokens
        ),
        default=0.0,
    )
    return round(100 * (0.8 * skill_coverage + 0.2 * target_overlap))


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding dimensions must match")
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return (
        sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0
    )


def score_match(
    resume_vector: list[float],
    role_vector: list[float],
    student_skills: set[str],
    required_skills: set[str],
    project_evidence: float,
) -> MatchResult:
    semantic = max(0.0, min(1.0, cosine(resume_vector, role_vector)))
    normalized_student = {item.casefold() for item in student_skills}
    normalized_required = {item.casefold() for item in required_skills}
    coverage = (
        len(normalized_student & normalized_required) / len(normalized_required)
        if normalized_required
        else 1.0
    )
    evidence = max(0.0, min(1.0, project_evidence))
    score = round((semantic * 0.6 + coverage * 0.3 + evidence * 0.1) * 100)
    return MatchResult(score, semantic, coverage, evidence, "match-v1")


def qdrant_payload(
    institution_id: str, student_id: str, resume_version: str, model: str
) -> dict[str, str]:
    return {
        "institution_id": institution_id,
        "student_id": student_id,
        "resume_version": resume_version,
        "embedding_model": model,
        "embedding_version": "v1",
    }
