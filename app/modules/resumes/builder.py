from io import BytesIO
from urllib.parse import urlparse

import pymupdf
from pydantic import BaseModel, Field


class ResumeContent(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str = Field(max_length=320)
    phone: str | None = Field(default=None, max_length=24)
    github_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    summary: str = Field(default="", max_length=900)
    skills: list[str] = Field(default_factory=list, max_length=40)
    projects: list[str] = Field(default_factory=list, max_length=10)
    education: list[str] = Field(default_factory=list, max_length=6)


def readiness_score(content: ResumeContent) -> tuple[int, dict[str, int]]:
    components = {
        "identity": 20 if content.full_name and content.email else 0,
        "summary": 15 if len(content.summary.split()) >= 20 else 0,
        "skills": 20 if len(content.skills) >= 4 else min(len(content.skills) * 5, 20),
        "projects": 25 if len(content.projects) >= 2 else len(content.projects) * 12,
        "education": 10 if content.education else 0,
        "evidence_links": 10 if content.github_url or content.portfolio_url else 0,
    }
    return sum(components.values()), components


def suggestion_is_supported(proposed: str, known_facts: set[str]) -> bool:
    lowered = proposed.casefold()
    suspicious = {"increased", "reduced", "million", "award", "certified"}
    return not any(term in lowered and term not in known_facts for term in suspicious)


def generate_pdf(content: ResumeContent) -> bytes:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page(width=595, height=842)
    y = 52
    page.insert_text((48, y), content.full_name, fontsize=20, fontname="helv")
    y += 22
    contacts = [content.email, content.phone, content.github_url, content.portfolio_url]
    page.insert_text((48, y), "  •  ".join(value for value in contacts if value), fontsize=9)
    y += 30
    for title, values in (
        ("SUMMARY", [content.summary] if content.summary else []),
        ("SKILLS", [", ".join(content.skills)] if content.skills else []),
        ("PROJECTS", content.projects),
        ("EDUCATION", content.education),
    ):
        if not values:
            continue
        page.insert_text((48, y), title, fontsize=10, fontname="helv")
        y += 16
        for value in values:
            page.insert_textbox((48, y, 547, y + 45), value, fontsize=9, lineheight=1.25)
            y += 48
    for link in (content.github_url, content.portfolio_url):
        if link and urlparse(link).scheme == "https":
            page.insert_link(
                {
                    "kind": pymupdf.LINK_URI,
                    "from": pymupdf.Rect(48, 62, 547, 84),  # type: ignore[no-untyped-call]
                    "uri": link,
                }
            )
    output = BytesIO()
    document.save(output)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return output.getvalue()
