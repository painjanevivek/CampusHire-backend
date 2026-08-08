import pymupdf

from app.modules.resumes.builder import (
    ResumeContent,
    generate_pdf,
    readiness_score,
    suggestion_is_supported,
)


def content() -> ResumeContent:
    return ResumeContent(
        full_name="Asha Patil",
        email="asha@example.edu",
        github_url="https://github.com/asha",
        summary=(
            "Computer science student building reliable data products with Python, SQL, "
            "thoughtful testing, and clear documentation for campus projects."
        ),
        skills=["Python", "SQL", "FastAPI", "React"],
        projects=["Placement matcher with deterministic eligibility", "Student roadmap dashboard"],
        education=["B.Tech Computer Science · Campus Institute · 2027"],
    )


def test_generated_pdf_has_selectable_identity_and_links() -> None:
    document = pymupdf.open(stream=generate_pdf(content()), filetype="pdf")
    assert "Asha Patil" in document[0].get_text()
    assert document[0].get_links()
    document.close()


def test_readiness_rubric_is_componentized_and_versionable() -> None:
    score, components = readiness_score(content())
    assert score >= 85
    assert set(components) == {
        "identity",
        "summary",
        "skills",
        "projects",
        "education",
        "evidence_links",
    }


def test_suggestion_rejects_unsupported_achievement_claim() -> None:
    assert not suggestion_is_supported("Increased conversion by 40%", set())
