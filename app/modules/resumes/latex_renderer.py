"""Deterministic, bounded LaTeX rendering for reviewed resume evidence."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, cast
from urllib.parse import quote, urlsplit, urlunsplit

import pymupdf

from app.modules.resumes.builder import (
    ResumeBuildError,
    ResumeContent,
    ResumeEntry,
    ResumeSection,
    evidence_digest,
)

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

TEMPLATE_ID = "campushire-modern"
TEMPLATE_VERSION = "1"
GENERATOR_VERSION = f"{TEMPLATE_ID}-v{TEMPLATE_VERSION}"
TEMPLATE_RESOURCE = "templates/campushire_modern_v1.tex"
PDF_LIMIT = 5 * 1024 * 1024
DATE_PATTERN = re.compile(r"(?i)(?:19|20)\d{2}|present|current|now")
MISSING_DEPENDENCY_PATTERN = re.compile(
    r"(?m)! LaTeX Error: File [`']([A-Za-z0-9._-]+\.sty)['`] not found\."
)

_LATEX_ESCAPE = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(value: str) -> str:
    """Escape all LaTeX control characters in untrusted text."""
    return "".join(_LATEX_ESCAPE.get(character, character) for character in value)


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\x00", "").split())


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        if any(ord(character) < 32 for character in value):
            return None
        host = parsed.hostname.encode("idna").decode("ascii")
        if parsed.port:
            host = f"{host}:{parsed.port}"
        path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
        query = quote(parsed.query, safe="/?@!$&'()*+,;=:-._~")
        fragment = quote(parsed.fragment, safe="/?@!$&'()*+,;=:-._~")
        return urlunsplit((parsed.scheme.lower(), host, path, query, fragment))
    except (UnicodeError, ValueError):
        return None


def _href(url: str, label: str) -> str:
    # URL fields are parsed and normalized before reaching this formatter.
    safe_argument = url.translate(
        {
            ord("%"): r"\%",
            ord("#"): r"\#",
            ord("&"): r"\&",
            ord("_"): r"\_",
            ord("$"): r"\$",
            ord("{"): r"\{",
            ord("}"): r"\}",
        }
    )
    return rf"\href{{{safe_argument}}}{{{latex_escape(label)}}}"


def _render_entry(item: ResumeEntry | str, section: str) -> str:
    if isinstance(item, str):
        # Legacy profile fields are human-readable strings. Preserve their common
        # separators so a role/date is rendered as metadata instead of a bullet.
        parts = [_clean_text(part) for part in re.split(r"\s+[—–]\s+", item) if _clean_text(part)]
        if not parts:
            return ""
        title = parts[0]
        organization = ""
        dates = ""
        details: list[str] = []
        if section == "education":
            metadata_source = " · ".join(parts[1:]) if len(parts) > 1 else parts[0]
            metadata = [_clean_text(part) for part in re.split(r"\s*[·•]\s*", metadata_source)]
            if len(parts) == 1 and metadata:
                title = metadata.pop(0)
            organization = metadata[0] if metadata else ""
            if organization:
                metadata.pop(0)
            if len(metadata) > 1 and DATE_PATTERN.search(metadata[-1]):
                dates = metadata.pop()
            elif metadata and DATE_PATTERN.search(metadata[-1]):
                dates = metadata.pop()
            details = [*metadata, *parts[2:]]
        elif section == "experience" and len(parts) > 1:
            metadata = [_clean_text(part) for part in re.split(r"\s*[·•]\s*", parts[1])]
            if len(metadata) > 1 and DATE_PATTERN.search(metadata[-1]):
                dates = metadata.pop()
            organization = metadata[0] if metadata else ""
            details = [*metadata[1:], *parts[2:]]
        else:
            details = parts[1:]
        entry_url = next((part for part in details if _safe_url(part)), None)
        details = [part for part in details if part != entry_url]
        bullets = [latex_escape(detail) for detail in details]
        heading = latex_escape(title)
        if entry_url:
            heading = _href(_safe_url(entry_url) or "", title)
        rendered = [
            rf"\entryheading{{{heading}}}{{{latex_escape(organization)}}}"
            rf"{{{latex_escape(dates)}}}{{}}"
        ]
        if bullets:
            rendered.append(
                r"\begin{itemize}"
                + "\n"
                + "\n".join(rf"\item {value}" for value in bullets)
                + "\n"
                + r"\end{itemize}"
            )
        return "\n".join(rendered)

    title = _clean_text(item.title)
    if not title:
        return ""
    subtitle = " · ".join(
        value
        for value in (_clean_text(item.organization or ""), _clean_text(item.location or ""))
        if value
    )
    date = " – ".join(
        value
        for value in (_clean_text(item.start_date or ""), _clean_text(item.end_date or ""))
        if value
    )
    title_rendered = latex_escape(title)
    safe_url = _safe_url(item.url)
    if safe_url:
        title_rendered = _href(safe_url, title)
    rendered = [
        rf"\entryheading{{{title_rendered}}}{{{latex_escape(subtitle)}}}"
        rf"{{{latex_escape(date)}}}{{}}"
    ]
    detail_items = [item.description, *item.bullets]
    technologies = ", ".join(
        _clean_text(value) for value in item.technologies if _clean_text(value)
    )
    if technologies:
        detail_items.append(f"Technologies: {technologies}")
    bullets = [latex_escape(_clean_text(value)) for value in detail_items if _clean_text(value)]
    if bullets:
        rendered.append(
            r"\begin{itemize}"
            + "\n"
            + "\n".join(rf"\item {value}" for value in bullets)
            + "\n"
            + r"\end{itemize}"
        )
    return "\n".join(rendered)


def _section(title: str, entries: list[str]) -> str:
    populated = [entry for entry in entries if entry]
    if not populated:
        return ""
    return "\n".join([rf"\sectionline{{{latex_escape(title)}}}", *populated])


def _section_map(content: ResumeContent) -> dict[ResumeSection, tuple[str, list[str]]]:
    values: dict[ResumeSection, tuple[str, list[str]]] = {
        "experience": (
            "Experience",
            [_render_entry(item, "experience") for item in content.experience],
        ),
        "projects": ("Projects", [_render_entry(item, "projects") for item in content.projects]),
        "education": (
            "Education",
            [_render_entry(item, "education") for item in content.education],
        ),
        "research": ("Research", [_render_entry(item, "research") for item in content.research]),
        "publications": (
            "Publications",
            [_render_entry(item, "publications") for item in content.publications],
        ),
        "certifications": (
            "Certifications",
            [_render_entry(item, "certifications") for item in content.certifications],
        ),
        "achievements": (
            "Achievements",
            [_render_entry(item, "achievements") for item in content.achievements],
        ),
        "positions": (
            "Positions of Responsibility",
            [_render_entry(item, "positions") for item in content.positions],
        ),
        "extracurricular": (
            "Extracurricular",
            [_render_entry(item, "extracurricular") for item in content.extracurricular],
        ),
    }
    if content.credentials:
        title = "Research, Publications, Open Source & Certifications"
        if content.research or content.publications or content.certifications:
            values["certifications"] = (
                "Certifications & Additional Credentials",
                [
                    *values["certifications"][1],
                    *(_render_entry(item, "certifications") for item in content.credentials),
                ],
            )
        else:
            values["certifications"] = (
                title,
                [_render_entry(item, "certifications") for item in content.credentials],
            )
    skill_lines: list[str] = []
    groups = content.skill_groups or []
    if not groups and content.skills:
        from app.modules.resumes.builder import SkillGroup

        groups = [SkillGroup(category="Other", items=content.skills)]
    for group in groups:
        items = [latex_escape(_clean_text(value)) for value in group.items if _clean_text(value)]
        if items:
            skill_lines.append(rf"\textbf{{{latex_escape(group.category)}}}: " + ", ".join(items))
    values["skills"] = ("Skills", skill_lines)
    return values


def _contact_lines(content: ResumeContent) -> list[str]:
    lines = [
        rf"\href{{mailto:{latex_escape(content.email)}}}{{Email: {latex_escape(content.email)}}}"
    ]
    if content.phone:
        lines.insert(0, rf"\textbf{{Phone:}} {latex_escape(_clean_text(content.phone))}")
    for label, url in (
        ("GitHub", content.github_url),
        ("LinkedIn", content.linkedin_url),
        ("Portfolio", content.portfolio_url),
    ):
        safe = _safe_url(url)
        if safe:
            lines.append(_href(safe, label))
    return lines


def render_latex(content: ResumeContent, *, artifact_id: str | None = None) -> str:
    """Render the versioned LaTeX template using only validated structured data."""
    resource = files("app.modules.resumes").joinpath(TEMPLATE_RESOURCE)
    try:
        template = resource.read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError) as error:
        raise ResumeBuildError("resume_template_unavailable") from error

    digest = evidence_digest(content)
    links = _contact_lines(content)
    header = "\n".join(
        [
            r"\begin{center}",
            rf"{{\LARGE\bfseries {latex_escape(_clean_text(content.full_name))}}}\par",
            r"\vspace{4pt}",
            r" \textbar{} ".join(links),
            r"\end{center}",
        ]
    )
    summary = (
        _section("Summary", [latex_escape(_clean_text(content.summary))])
        if _clean_text(content.summary)
        else ""
    )
    sections = _section_map(content)
    order: list[ResumeSection] = list(content.section_order)
    order.extend(section for section in sections if section not in order)
    rendered_sections = "\n".join(
        _section(sections[key][0], sections[key][1]) for key in order if key in sections
    )
    metadata = (
        r"\hypersetup{"
        + f"pdftitle={{{latex_escape(_clean_text(content.full_name) + ' - reviewed resume')}}},"
        + f"pdfauthor={{{latex_escape(_clean_text(content.full_name))}}},"
        + "pdfsubject={Student-reviewed CampusHire resume},"
        + f"pdfkeywords={{campushire-evidence-sha256:{digest}"
        + (f"; artifact:{latex_escape(artifact_id)}" if artifact_id else "")
        + "}}"
    )
    replacements = {
        "%%RESUME_HEADER%%": header,
        "%%RESUME_SUMMARY%%": summary,
        "%%RESUME_SECTIONS%%": rendered_sections,
        "%%RESUME_METADATA%%": metadata,
    }
    for marker, rendered in replacements.items():
        if template.count(marker) != 1:
            raise ResumeBuildError("resume_template_invalid")
        template = template.replace(marker, rendered)
    if "%%RESUME_" in template:
        raise ResumeBuildError("resume_template_invalid")
    return template


def compile_resume_pdf(
    content: ResumeContent,
    *,
    settings: Settings,
    artifact_id: str | None = None,
) -> bytes:
    """Compile and validate one PDF in a temporary directory with no shell escape."""
    latex_source = render_latex(content, artifact_id=artifact_id)
    engine_name = settings.resume_latex_engine
    engine = shutil.which(engine_name)
    if engine is None:
        raise ResumeBuildError("resume_latex_compiler_unavailable")

    command = [engine]
    if settings.resume_latex_distribution == "miktex":
        command.extend(("--disable-installer", "--disable-write18"))
    else:
        command.append("-no-shell-escape")
    command.extend(
        (
            "-halt-on-error",
            "-interaction=nonstopmode",
            "-file-line-error",
            "-jobname=resume",
            "resume.tex",
        )
    )
    with tempfile.TemporaryDirectory(prefix="campushire-resume-") as directory:
        workdir = Path(directory)
        (workdir / "resume.tex").write_text(latex_source, encoding="utf-8", newline="\n")
        log_path = workdir / "compile.log"
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "LOCALAPPDATA",
                "APPDATA",
                "USERPROFILE",
                "HOME",
            }
        }
        try:
            with log_path.open("wb") as log_file:
                result = subprocess.run(  # noqa: S603 - fixed compiler choice; no shell is used.
                    command,
                    cwd=workdir,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=settings.resume_latex_timeout_seconds,
                    shell=False,
                    close_fds=True,
                )
        except subprocess.TimeoutExpired as error:
            logger.warning("resume_latex_timeout", extra={"event": "resume_latex_timeout"})
            raise ResumeBuildError("resume_latex_timeout") from error
        except OSError as error:
            logger.error(
                "resume_latex_compiler_unavailable",
                extra={
                    "event": "resume_latex_compiler_unavailable",
                    "exception_type": type(error).__name__,
                },
            )
            raise ResumeBuildError("resume_latex_compiler_unavailable") from error

        pdf_path = workdir / "resume.pdf"
        if result.returncode != 0 or not pdf_path.is_file():
            try:
                compiler_log = log_path.read_text(encoding="utf-8", errors="replace")[-32_768:]
            except OSError:
                compiler_log = ""
            error_code = (
                "resume_latex_dependency_missing"
                if MISSING_DEPENDENCY_PATTERN.search(compiler_log)
                else "resume_latex_compile_failed"
            )
            logger.warning(
                error_code,
                extra={"event": error_code, "return_code": result.returncode},
            )
            raise ResumeBuildError(error_code)
        if pdf_path.stat().st_size > min(settings.resume_generated_max_bytes, PDF_LIMIT):
            raise ResumeBuildError("resume_pdf_too_large")
        data = pdf_path.read_bytes()

    try:
        document = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
        if document.page_count < 1:
            raise ResumeBuildError("resume_pdf_invalid")
        expected_name = _clean_text(content.full_name)
        first_page_text = _clean_text(document[0].get_text())  # type: ignore[no-untyped-call]
        if expected_name.casefold() not in first_page_text.casefold():
            raise ResumeBuildError("resume_pdf_invalid")
        document.close()  # type: ignore[no-untyped-call]
    except ResumeBuildError:
        raise
    except Exception as error:
        raise ResumeBuildError("resume_pdf_invalid") from error
    return data


def generated_pdf_page_count(data: bytes) -> int:
    """Return the verified page count of a generated PDF."""
    try:
        document = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
        page_count = cast(int, document.page_count)
        document.close()  # type: ignore[no-untyped-call]
        if page_count < 1:
            raise ResumeBuildError("resume_pdf_invalid")
        return page_count
    except ResumeBuildError:
        raise
    except Exception as error:
        raise ResumeBuildError("resume_pdf_invalid") from error
