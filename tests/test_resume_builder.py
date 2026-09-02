import pymupdf

from app.modules.resumes.builder import (
    ResumeContent,
    evidence_digest,
    generate_pdf,
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
    generated = generate_pdf(content())
    document = pymupdf.open(stream=generated, filetype="pdf")
    assert "Asha Patil" in document[0].get_text()
    assert document[0].get_links()
    assert document.metadata["producer"] == "CampusHire PDF Generator v1"
    assert document.metadata["keywords"] == f"campushire-evidence-sha256:{evidence_digest(content())}"
    assert "Evidence" in document[-1].get_text()
    document.close()
    assert generated == generate_pdf(content())


def test_generated_pdf_paginates_without_clipping_reviewed_content() -> None:
    long_content = content().model_copy(
        update={
            "projects": [f"Project {index}: " + "verified detail " * 45 for index in range(8)],
            "education": ["Reviewed education evidence " * 20],
        }
    )
    document = pymupdf.open(stream=generate_pdf(long_content), filetype="pdf")
    assert 1 < document.page_count <= 3
    assert "Project 7" in "".join(page.get_text() for page in document)
    document.close()


def test_suggestion_rejects_unsupported_achievement_claim() -> None:
    assert not suggestion_is_supported("Increased conversion by 40%", set())
