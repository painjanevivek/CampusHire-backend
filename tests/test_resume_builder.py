import pymupdf

from app.modules.resumes.builder import (
    ResumeContent,
    evidence_digest,
    generate_pdf,
    suggestion_is_supported,
)
from app.modules.resumes.latex_renderer import latex_escape, render_latex


def content() -> ResumeContent:
    return ResumeContent(
        full_name="Asha Patil",
        email="asha@example.edu",
        github_url="https://github.com/asha",
        linkedin_url="https://linkedin.com/in/asha",
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


def test_latex_escape_covers_control_characters() -> None:
    assert latex_escape("50% & $10_#1 {x} ~ ^ \\") == (
        r"50\% \& \$10\_\#1 \{x\} \textasciitilde{} "
        r"\textasciicircum{} \textbackslash{}"
    )


def test_template_uses_structured_sections_and_safe_links() -> None:
    source = render_latex(content())
    assert r"\href{https://github.com/asha}{GitHub}" in source
    assert r"\sectionline{Experience}" in source
    assert r"\sectionline{Projects}" in source
    assert source.index(r"\sectionline{Experience}") < source.index(r"\sectionline{Projects}")
    assert r"\entryheading{Campus coding club}{Volunteer}{2025–2026}{}" in source
    assert r"\entryheading{B.Tech Computer Science}{Campus Institute}{2027}{}" in source
    assert "campushire-evidence-sha256:" + evidence_digest(content()) in source


def test_template_omits_empty_sections_and_escapes_untrusted_text() -> None:
    value = ResumeContent(
        full_name="Asha & Dev_#1",
        email="asha@example.edu",
        summary=r"Built a 50% reliable tool & shipped code_1.",
        github_url="javascript:alert(1)",
    )
    source = render_latex(value)
    assert r"Asha \& Dev\_\#1" in source
    assert r"50\% reliable tool \& shipped code\_1" in source
    assert r"\href{javascript:" not in source
    assert r"\sectionline{Projects}" not in source
    assert r"\sectionline{Skills}" not in source


def test_template_preserves_explicit_section_order_and_optional_fields() -> None:
    value = ResumeContent(
        full_name="Asha Patil",
        email="asha@example.edu",
        research=["Campus accessibility survey"],
        publications=["Student computing journal, 2026"],
        positions=["Secretary — Computing Society"],
        extracurricular=["Robotics club — volunteer"],
        section_order=["positions", "research", "publications", "extracurricular"],
    )
    source = render_latex(value)
    headings = [
        r"\sectionline{Positions of Responsibility}",
        r"\sectionline{Research}",
        r"\sectionline{Publications}",
        r"\sectionline{Extracurricular}",
    ]
    offsets = [source.index(heading) for heading in headings]
    assert offsets == sorted(offsets)


def test_generated_pdf_has_selectable_identity_links_and_metadata() -> None:
    document = pymupdf.open(stream=generate_pdf(content()), filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    assert "Asha Patil" in text
    assert "Placement matcher" in text
    assert "Campus coding club" in text
    assert document[0].get_links()
    assert document.metadata["producer"] == "CampusHire LaTeX Resume Generator v1"
    assert evidence_digest(content()) in document.metadata["keywords"]
    document.close()


def test_generated_pdf_paginates_without_clipping_optional_content() -> None:
    long_content = content().model_copy(
        update={
            "projects": [f"Project {index}: " + "verified detail " * 40 for index in range(1, 11)],
            "education": ["Reviewed education evidence " * 15],
            "experience": ["Reviewed work evidence " * 30],
        }
    )
    document = pymupdf.open(stream=generate_pdf(long_content), filetype="pdf")
    text = "\n".join(page.get_text() for page in document)
    assert document.page_count > 1
    assert "Project 10" in text
    assert "Reviewed work evidence" in text
    document.close()


def test_suggestion_rejects_unsupported_achievement_claim() -> None:
    assert not suggestion_is_supported("Increased conversion by 40%", set())
