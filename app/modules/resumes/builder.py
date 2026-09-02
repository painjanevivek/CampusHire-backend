import hashlib
import json
import textwrap
from io import BytesIO
from typing import Annotated
from urllib.parse import urlparse

import pymupdf
from pydantic import BaseModel, Field

SkillText = Annotated[str, Field(min_length=1, max_length=120)]
ProjectText = Annotated[str, Field(min_length=1, max_length=1_200)]
EducationText = Annotated[str, Field(min_length=1, max_length=800)]


class ResumeBuildError(RuntimeError):
    pass


class ResumeContent(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: str = Field(max_length=320)
    phone: str | None = Field(default=None, max_length=24)
    github_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    summary: str = Field(default="", max_length=900)
    skills: list[SkillText] = Field(default_factory=list, max_length=40)
    projects: list[ProjectText] = Field(default_factory=list, max_length=10)
    education: list[EducationText] = Field(default_factory=list, max_length=6)


def suggestion_is_supported(proposed: str, known_facts: set[str]) -> bool:
    lowered = proposed.casefold()
    suspicious = {"increased", "reduced", "million", "award", "certified"}
    return not any(term in lowered and term not in known_facts for term in suspicious)


def evidence_digest(content: ResumeContent) -> str:
    canonical = json.dumps(
        content.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def generate_pdf(content: ResumeContent) -> bytes:
    content_digest = evidence_digest(content)
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.set_metadata(
        {
            "title": f"{content.full_name} - reviewed resume",
            "author": content.full_name,
            "subject": "Student-reviewed CampusHire resume",
            "keywords": f"campushire-evidence-sha256:{content_digest}",
            "creator": "CampusHire AI",
            "producer": "CampusHire PDF Generator v1",
            "creationDate": "D:20000101000000Z",
            "modDate": "D:20000101000000Z",
        }
    )
    page: pymupdf.Page | None = None
    y = 0.0

    def new_page() -> None:
        nonlocal page, y
        if document.page_count >= 3:
            raise ResumeBuildError("resume_generated_page_limit")
        page = document.new_page(width=595, height=842)
        y = 52

    def ensure_space(height: float) -> None:
        if page is None or y + height > 780:
            new_page()

    def write_lines(value: str, *, font_size: float = 9, bold: bool = False) -> None:
        nonlocal y
        lines = textwrap.wrap(value, width=96, break_long_words=True) or [""]
        ensure_space(len(lines) * 12 + 4)
        assert page is not None
        for line in lines:
            page.insert_text(
                (48, y), line, fontsize=font_size, fontname="hebo" if bold else "helv"
            )
            y += 12
        y += 4

    new_page()
    write_lines(content.full_name, font_size=20, bold=True)
    contacts = [content.email, content.phone, content.github_url, content.portfolio_url]
    for contact in (value for value in contacts if value):
        ensure_space(16)
        assert page is not None
        link_top = y - 9
        write_lines(contact)
        if urlparse(contact).scheme == "https":
            page.insert_link(
                {
                    "kind": pymupdf.LINK_URI,
                    "from": pymupdf.Rect(48, link_top, 547, y),  # type: ignore[no-untyped-call]
                    "uri": contact,
                }
            )
    y += 10
    for title, values in (
        ("SUMMARY", [content.summary] if content.summary else []),
        ("SKILLS", [", ".join(content.skills)] if content.skills else []),
        ("PROJECTS", content.projects),
        ("EDUCATION", content.education),
    ):
        if not values:
            continue
        ensure_space(30)
        write_lines(title, font_size=10, bold=True)
        for value in values:
            write_lines(value)
    for page_index in range(document.page_count):
        current_page = document[page_index]
        current_page.insert_text(
            (48, 812),
            f"CampusHire reviewed resume | Evidence {content_digest[:12]}",
            fontsize=7,
            fontname="helv",
            color=(0.25, 0.29, 0.38),
        )
    output = BytesIO()
    document.save(output, garbage=4, deflate=True, no_new_id=True)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return output.getvalue()
