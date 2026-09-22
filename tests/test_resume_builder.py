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
        experience=["Campus coding club — Volunteer · 2025–2026"],
        credentials=["AWS Foundations — Certificate of completion · 2026"],
        achievements=["Winner, inter-college engineering hackathon"],
    )


def test_generated_pdf_has_selectable_identity_and_links() -> None:
    generated = generate_pdf(content())
    document = pymupdf.open(stream=generated, filetype="pdf")
    assert "Asha Patil" in document[0].get_text()
    assert document[0].get_links()
    assert document.metadata["producer"] == "CampusHire PDF Generator v2"
    assert document.metadata["keywords"] == (
        f"campushire-evidence-sha256:{evidence_digest(content())}"
    )
    assert "Evidence" in document[-1].get_text()
    document.close()
    assert generated == generate_pdf(content())


def test_generated_pdf_uses_classic_template_section_order() -> None:
    document = pymupdf.open(stream=generate_pdf(content()), filetype="pdf")
    text = "\n".join(page.get_text() for page in document)

    headings = [
        "PROJECTS",
        "EDUCATION",
        "EXPERIENCE",
        "OPEN SOURCE, RESEARCH, AND CERTIFICATION",
        "SKILLS AND ACHIEVEMENTS",
    ]
    offsets = [text.index(heading) for heading in headings]

    assert offsets == sorted(offsets)
    assert "Phone:" not in text
    assert "Email: asha@example.edu" in text
    assert "Campus coding club" in text
    assert "AWS Foundations" in text
    assert "Winner, inter-college engineering hackathon" in text
    document.close()


def test_generated_pdf_omits_empty_optional_sections() -> None:
    minimal = ResumeContent(full_name="Asha Patil", email="asha@example.edu")
    document = pymupdf.open(stream=generate_pdf(minimal), filetype="pdf")
    text = "\n".join(page.get_text() for page in document)

    assert "PROJECTS" not in text
    assert "SKILLS AND ACHIEVEMENTS" not in text
    assert document.page_count == 1
    document.close()


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
