"""Readiness rules for generating a CampusHire resume from reviewed student evidence."""

from app.modules.resumes.builder import ResumeContent, ResumeEntry


def _has_entries(items: list[ResumeEntry | str]) -> bool:
    return any(
        item.title.strip() if isinstance(item, ResumeEntry) else item.strip() for item in items
    )


def resume_readiness(content: ResumeContent) -> dict[str, list[str] | bool]:
    blocking: list[str] = []
    warnings: list[str] = []
    informational: list[str] = []

    if not content.full_name.strip():
        blocking.append("Add your name.")
    if not content.email.strip():
        blocking.append("Add a valid email address.")
    if not _has_entries(content.education):
        blocking.append("Add at least one education entry.")

    if not _has_entries(content.projects):
        warnings.append("Add a project to show practical work.")
    if not _has_entries(content.experience):
        warnings.append("Add experience if you have it.")
    if not content.skills and not any(group.items for group in content.skill_groups):
        warnings.append("Add relevant skills.")
    if not content.github_url:
        warnings.append("Add GitHub if you have a profile to share.")
    if not content.linkedin_url:
        warnings.append("Add LinkedIn if you have a profile to share.")
    if not content.portfolio_url:
        warnings.append("Add a portfolio link if you have one.")
    if not (content.certifications or content.credentials):
        informational.append("Research, publications, and certifications are optional.")

    return {
        "ready": not blocking,
        "blocking": blocking,
        "warnings": warnings,
        "informational": informational,
    }
