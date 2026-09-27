from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.generative.resume_studio import (
    _resume_content_from_proposal,
    _validate_evidence_snapshot,
)
from app.modules.generative.schemas import EvidenceReference, GroundedClaim, ResumeDraft
from app.modules.generative.service import ProposalValidationError
from app.modules.resumes.builder import generate_pdf
from app.modules.resumes.latex_renderer import GENERATOR_VERSION, render_latex


def test_ai_resume_keeps_manual_builder_sections_and_profile_metadata() -> None:
    profile_id = uuid4()
    project_id = uuid4()
    experience_id = uuid4()
    certification_id = uuid4()
    profile = SimpleNamespace(
        id=profile_id,
        full_name="Test Student",
        phone="9876543210",
        external_links={
            "github": "https://github.com/test-student",
            "linkedin": "https://linkedin.com/in/test-student",
            "portfolio": "https://example.com",
        },
        education=[],
    )
    education = [
        SimpleNamespace(
            id=uuid4(),
            degree="B.Tech",
            branch="Computer Science",
            institution="Example Institute",
            start_year=2022,
            graduation_year=2026,
            score=8.5,
            score_scale="cgpa_10",
        )
    ]
    school_record_id = uuid4()
    education.append(SimpleNamespace(
        id=school_record_id, qualification_level="class_10", degree="Class 10",
        branch="General", institution="School", start_year=None,
        graduation_year=2021, score=89.0, score_scale="percentage",
    ))
    projects = [
        SimpleNamespace(
            id=project_id,
            title="Placement Portal",
            description="Built a student portal",
            technologies=["Python", "React"],
            project_url="https://example.com/project",
        )
    ]
    experience = [
        SimpleNamespace(
            id=experience_id,
            title="Software Intern",
            organization="Example Co",
            start_date=date(2025, 6, 1),
            end_date=date(2025, 8, 1),
            is_current=False,
        )
    ]
    certifications = [
        SimpleNamespace(
            id=certification_id,
            name="Cloud Fundamentals",
            issuer="Example Academy",
            issued_on=date(2025, 1, 1),
        )
    ]
    draft = ResumeDraft(
        professional_summary=GroundedClaim(
            text="Computer science student with Python project experience.",
            evidence_ids=[f"project:{project_id}"],
        ),
        strengths=[
            GroundedClaim(text="Python and React", evidence_ids=[f"project:{project_id}"])
        ],
        project_bullets=[
            GroundedClaim(
                text="Built the portal with Python and React",
                evidence_ids=[f"project:{project_id}"],
            )
        ],
        experience_bullets=[
            GroundedClaim(
                text="Developed API tests",
                evidence_ids=[f"experience:{experience_id}"],
            )
        ],
        skills=[
            GroundedClaim(
                text="Python", evidence_ids=[f"profile:{profile_id}:skill:0"]
            )
        ],
    )

    content = _resume_content_from_proposal(
        profile=profile,
        account_email="student@example.edu",
        education=education,
        projects=projects,
        experience=experience,
        certifications=certifications,
        evidence_ids={
            f"project:{project_id}",
            f"experience:{experience_id}",
            f"certification:{certification_id}",
        },
        draft=draft,
    )

    assert content.linkedin_url == "https://linkedin.com/in/test-student"
    assert content.education == [
        "B.Tech Computer Science — Example Institute · 2022–2026 — CGPA: 8.5/10"
    ]
    assert content.projects == [
        "Placement Portal — Built the portal with Python and React — "
        "Technologies: Python, React — https://example.com/project"
    ]
    assert content.experience == [
        "Software Intern — Example Co · 2025-06-01–2025-08-01 — Developed API tests"
    ]
    assert content.certifications == ["Cloud Fundamentals — Example Academy — 2025-01-01"]
    assert content.strengths == ["Python and React"]
    assert GENERATOR_VERSION == "campushire-modern-v2"
    rendered = render_latex(content)
    assert "Placement Portal" in rendered
    assert "Example Institute" in rendered
    assert "Cloud Fundamentals" in rendered
    assert "Professional Summary" in rendered
    assert "Strengths" in rendered
    assert "Python and React" in rendered
    assert generate_pdf(content).startswith(b"%PDF-")


def test_changed_selected_profile_evidence_requires_a_new_proposal() -> None:
    original = EvidenceReference(
        evidence_id="project:1", kind="project", label="Portal", facts="Used Python"
    )
    current = original.model_copy(update={"facts": "Used Python and React"})
    with pytest.raises(ProposalValidationError, match="profile details changed"):
        _validate_evidence_snapshot([original.model_dump(mode="json")], [current])


def test_ai_resume_requires_education_before_queuing_pdf() -> None:
    profile = SimpleNamespace(
        id=uuid4(), full_name="Test Student", phone=None, external_links={}, education=[]
    )
    with pytest.raises(ProposalValidationError, match="Add education"):
        _resume_content_from_proposal(
            profile=profile,
            account_email="student@example.edu",
            education=[],
            projects=[],
            experience=[],
            certifications=[],
            evidence_ids=set(),
            draft=ResumeDraft(),
        )
