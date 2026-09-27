import pytest
from pydantic import ValidationError

from app.modules.onboarding.schemas import StudentOnboardingUpdate

DEGREE = {
    "qualification_level": "degree",
    "degree": "BTech",
    "branch": "Computer Engineering",
    "institution": "Campus Institute",
    "graduation_year": 2027,
    "score": 8.2,
    "score_scale": "cgpa_10",
}
CLASS_10 = {
    "qualification_level": "class_10",
    "degree": "Class 10",
    "branch": "General",
    "institution": "School",
    "graduation_year": 2021,
    "score": 89.0,
    "score_scale": "percentage",
}
CLASS_12 = {
    "qualification_level": "class_12",
    "degree": "Class 12",
    "branch": "Science",
    "institution": "Junior College",
    "graduation_year": 2023,
    "score": 85.0,
    "score_scale": "percentage",
}
DIPLOMA = {
    "qualification_level": "diploma",
    "degree": "Diploma",
    "branch": "Computer Engineering",
    "institution": "Polytechnic",
    "graduation_year": 2023,
    "score": 83.0,
    "score_scale": "percentage",
}


@pytest.mark.parametrize("alternative", [CLASS_12, DIPLOMA])
def test_academic_records_require_tenth_and_either_twelfth_or_diploma(alternative: dict) -> None:
    payload = StudentOnboardingUpdate(
        expected_revision=1, step=2, education=[DEGREE, CLASS_10, alternative]
    )
    assert len(payload.education or []) == 3


@pytest.mark.parametrize("missing", [[DEGREE], [DEGREE, CLASS_10], [DEGREE, CLASS_12]])
def test_academic_records_reject_missing_school_marks(missing: list[dict]) -> None:
    with pytest.raises(ValidationError, match="Class 10.*Class 12 or diploma"):
        StudentOnboardingUpdate(expected_revision=1, step=2, education=missing)
