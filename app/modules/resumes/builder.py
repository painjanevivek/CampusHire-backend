import hashlib
import json
from io import BytesIO
from typing import Annotated
from urllib.parse import urlparse

import pymupdf
from pydantic import BaseModel, Field

SkillText = Annotated[str, Field(min_length=1, max_length=120)]
ProjectText = Annotated[str, Field(min_length=1, max_length=1_200)]
EducationText = Annotated[str, Field(min_length=1, max_length=800)]
ExperienceText = Annotated[str, Field(min_length=1, max_length=1_200)]
CredentialText = Annotated[str, Field(min_length=1, max_length=1_000)]
AchievementText = Annotated[str, Field(min_length=1, max_length=500)]


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
    experience: list[ExperienceText] = Field(default_factory=list, max_length=10)
    credentials: list[CredentialText] = Field(default_factory=list, max_length=12)
    achievements: list[AchievementText] = Field(default_factory=list, max_length=12)


def suggestion_is_supported(proposed: str, known_facts: set[str]) -> bool:
    lowered = proposed.casefold()
    suspicious = {"increased", "reduced", "million", "award", "certified"}
    return not any(term in lowered and term not in known_facts for term in suspicious)


def evidence_digest(content: ResumeContent) -> str:
    canonical = json.dumps(
        content.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def generate_pdf(content: ResumeContent, *, artifact_id: str | None = None) -> bytes:
    """Render the reviewed content with the CampusHire Classic A4 resume template."""
    content_digest = evidence_digest(content)
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.set_metadata(
        {
            "title": f"{content.full_name} - reviewed resume",
            "author": content.full_name,
            "subject": "Student-reviewed CampusHire resume",
            "keywords": (
                f"campushire-evidence-sha256:{content_digest}"
                + (f"; artifact:{artifact_id}" if artifact_id else "")
            ),
            "creator": "CampusHire",
            "producer": "CampusHire PDF Generator v2",
            "creationDate": "D:20000101000000Z",
            "modDate": "D:20000101000000Z",
        }
    )
    page_width = 595.0
    page_height = 842.0
    left = 36.0
    right = page_width - 36.0
    content_bottom = 806.0
    body_font = "tiro"
    bold_font = "tibo"
    italic_font = "tiit"
    body_size = 9.4
    line_height = 11.6
    page: pymupdf.Page | None = None
    y = 0.0

    def new_page() -> None:
        nonlocal page, y
        if document.page_count >= 3:
            raise ResumeBuildError("resume_generated_page_limit")
        page = document.new_page(width=page_width, height=page_height)
        y = 36.0

    def ensure_space(height: float) -> None:
        if page is None or y + height > content_bottom:
            new_page()

    def wrap_lines(
        value: str,
        *,
        font_name: str = body_font,
        font_size: float = body_size,
        max_width: float | None = None,
    ) -> list[str]:
        available = max_width or (right - left)
        paragraphs = value.replace("\r", "").split("\n") or [""]
        wrapped: list[str] = []
        for paragraph in paragraphs:
            words: list[str] = []
            for token in paragraph.split():
                if pymupdf.get_text_length(
                    token, fontname=font_name, fontsize=font_size
                ) <= available:
                    words.append(token)
                    continue
                chunk = ""
                for character in token:
                    candidate = f"{chunk}{character}"
                    if chunk and pymupdf.get_text_length(
                        candidate, fontname=font_name, fontsize=font_size
                    ) > available:
                        words.append(chunk)
                        chunk = character
                    else:
                        chunk = candidate
                if chunk:
                    words.append(chunk)
            if not words:
                wrapped.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                candidate_width = pymupdf.get_text_length(
                    candidate, fontname=font_name, fontsize=font_size
                )
                if candidate_width <= available:
                    current = candidate
                else:
                    wrapped.append(current)
                    current = word
            wrapped.append(current)
        return wrapped

    def write_lines(
        value: str,
        *,
        font_size: float = body_size,
        font_name: str = body_font,
        indent: float = 0.0,
        hanging_indent: float = 0.0,
        after: float = 3.0,
    ) -> None:
        nonlocal y
        lines = wrap_lines(
            value,
            font_name=font_name,
            font_size=font_size,
            max_width=right - left - indent - hanging_indent,
        )
        ensure_space(len(lines) * line_height + after)
        assert page is not None
        for index, line in enumerate(lines):
            x = left + indent + (hanging_indent if index else 0.0)
            page.insert_text((x, y), line, fontsize=font_size, fontname=font_name)
            y += line_height
        y += after

    def write_centered(value: str, *, font_name: str, font_size: float) -> None:
        nonlocal y
        ensure_space(font_size + 7)
        assert page is not None
        width = pymupdf.get_text_length(value, fontname=font_name, fontsize=font_size)
        page.insert_text(
            ((page_width - width) / 2, y), value, fontsize=font_size, fontname=font_name
        )
        y += font_size + 7

    def contact_rows() -> list[list[tuple[str, str, str | None]]]:
        def display_contact(value: str) -> str:
            compact = value.removeprefix("https://").removeprefix("www.")
            return compact if len(compact) <= 58 else f"{compact[:55]}..."

        contacts: list[tuple[str, str, str | None]] = [
            ("Email", display_contact(content.email), f"mailto:{content.email}")
        ]
        if content.phone:
            contacts.insert(0, ("Phone", content.phone, None))
        if content.github_url:
            contacts.append(
                ("GitHub", display_contact(content.github_url), content.github_url)
            )
        if content.portfolio_url:
            contacts.append(
                ("Portfolio", display_contact(content.portfolio_url), content.portfolio_url)
            )
        rows: list[list[tuple[str, str, str | None]]] = []
        current: list[tuple[str, str, str | None]] = []
        current_width = 0.0
        separator_width = pymupdf.get_text_length("  |  ", fontname=body_font, fontsize=10)
        for item in contacts:
            label, value, _ = item
            item_width = pymupdf.get_text_length(
                f"{label}: {value}", fontname=body_font, fontsize=10
            )
            proposed_width = current_width + (separator_width if current else 0.0) + item_width
            if current and proposed_width > right - left:
                rows.append(current)
                current = []
                current_width = 0.0
            current.append(item)
            current_width += (separator_width if len(current) > 1 else 0.0) + item_width
        if current:
            rows.append(current)
        return rows

    def write_contact_row(items: list[tuple[str, str, str | None]]) -> None:
        nonlocal y
        ensure_space(16)
        assert page is not None
        separator = "  |  "
        segments: list[tuple[str, str, str | None]] = []
        for index, (label, value, href) in enumerate(items):
            if index:
                segments.append((separator, body_font, None))
            segments.extend(((f"{label}: ", bold_font, None), (value, body_font, href)))
        width = sum(
            pymupdf.get_text_length(text, fontname=font_name, fontsize=10)
            for text, font_name, _ in segments
        )
        x = max(left, (page_width - width) / 2)
        for text, font_name, href in segments:
            segment_width = pymupdf.get_text_length(text, fontname=font_name, fontsize=10)
            page.insert_text((x, y), text, fontsize=10, fontname=font_name)
            if href and urlparse(href).scheme in {"https", "mailto"}:
                page.insert_link(
                    {
                        "kind": pymupdf.LINK_URI,
                        "from": pymupdf.Rect(x, y - 10, x + segment_width, y + 2),  # type: ignore[no-untyped-call]
                        "uri": href,
                    }
                )
            x += segment_width
        y += 14

    def write_heading(title: str) -> None:
        nonlocal y
        ensure_space(34)
        assert page is not None
        page.insert_text((left, y), title, fontsize=14.5, fontname=body_font)
        y += 8
        page.draw_line((left, y), (right, y), color=(0.72, 0.72, 0.72), width=1)
        y += 17

    def write_entry(value: str) -> None:
        normalized = " ".join(value.split())
        if not normalized:
            return
        if " — " in normalized:
            title, detail = normalized.split(" — ", 1)
            write_lines(title, font_name=bold_font, after=1)
            write_lines(detail, font_name=italic_font, after=4)
            return
        write_lines(f"•  {normalized}", indent=7, hanging_indent=8, after=2)

    def write_section(title: str, values: list[str]) -> None:
        if not values:
            return
        write_heading(title)
        for value in values:
            write_entry(value)

    new_page()
    write_centered(content.full_name, font_name=bold_font, font_size=27)
    for row in contact_rows():
        write_contact_row(row)
    y += 18

    if content.summary:
        write_heading("PROFILE")
        write_lines(content.summary, font_name=italic_font, after=5)
    write_section("PROJECTS", content.projects)
    write_section("EDUCATION", content.education)
    write_section("EXPERIENCE", content.experience)
    write_section("RESEARCH, PUBLICATIONS, OPEN SOURCE, AND CERTIFICATIONS", content.credentials)
    skills_and_achievements = []
    if content.skills:
        skills_and_achievements.append(f"Skills: {', '.join(content.skills)}")
    skills_and_achievements.extend(content.achievements)
    write_section("SKILLS AND ACHIEVEMENTS", skills_and_achievements)

    for page_index in range(document.page_count):
        current_page = document[page_index]
        current_page.insert_text(
            (left, 825),
            f"CampusHire reviewed resume | Evidence {content_digest[:12]}",
            fontsize=6.5,
            fontname=body_font,
            color=(0.35, 0.35, 0.35),
        )
    output = BytesIO()
    document.save(output, garbage=4, deflate=True, no_new_id=True)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return output.getvalue()
