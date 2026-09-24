import pytest
from pydantic import ValidationError

from app.modules.resumes.builder import ResumeContent
from app.modules.resumes.readiness import resume_readiness


def test_readiness_blocks_missing_education_and_explains_optional_sections() -> None:
    content = ResumeContent(full_name="Asha Patil", email="asha@example.edu")

    result = resume_readiness(content)

    assert result["ready"] is False
    assert "Add at least one education entry." in result["blocking"]
    assert "Add a project to show practical work." in result["warnings"]
    assert "Research, publications, and certifications are optional." in result["informational"]


def test_readiness_is_ready_with_minimum_required_evidence() -> None:
    content = ResumeContent(
        full_name="Asha Patil",
        email="asha@example.edu",
        education=["B.Tech Computer Science — Example University"],
    )

    result = resume_readiness(content)

    assert result["ready"] is True
    assert result["blocking"] == []


def test_resume_content_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        ResumeContent(full_name="Asha Patil", email="not-an-email")
