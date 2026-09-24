import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.config import Settings, get_settings

SkillText = Annotated[str, Field(min_length=1, max_length=120)]
ProjectText = Annotated[str, Field(min_length=1, max_length=1_200)]
EducationText = Annotated[str, Field(min_length=1, max_length=800)]
ExperienceText = Annotated[str, Field(min_length=1, max_length=1_200)]
CredentialText = Annotated[str, Field(min_length=1, max_length=1_000)]
AchievementText = Annotated[str, Field(min_length=1, max_length=500)]


class ResumeBuildError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


SkillCategory = Literal[
    "Programming",
    "Frontend",
    "Backend",
    "Databases",
    "AI/ML",
    "Cloud & DevOps",
    "Analytics & SEO",
    "Tools",
    "Other",
]
ResumeSection = Literal[
    "experience",
    "projects",
    "education",
    "research",
    "publications",
    "certifications",
    "skills",
    "achievements",
    "positions",
    "extracurricular",
]


def _default_section_order() -> list[ResumeSection]:
    return [
        "experience",
        "projects",
        "education",
        "research",
        "publications",
        "certifications",
        "skills",
        "achievements",
        "positions",
        "extracurricular",
    ]


class ResumeEntry(BaseModel):
    """Structured resume evidence used by the renderer; it is not stored as raw LaTeX."""

    title: str = Field(min_length=1, max_length=200)
    organization: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=120)
    start_date: str | None = Field(default=None, max_length=40)
    end_date: str | None = Field(default=None, max_length=40)
    description: str = Field(default="", max_length=1_200)
    bullets: list[str] = Field(default_factory=list, max_length=12)
    technologies: list[SkillText] = Field(default_factory=list, max_length=20)
    url: str | None = Field(default=None, max_length=500)

    @field_validator(
        "title", "organization", "location", "start_date", "end_date", "description", "url"
    )
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("bullets")
    @classmethod
    def trim_bullets(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class SkillGroup(BaseModel):
    category: SkillCategory
    items: list[SkillText] = Field(default_factory=list, max_length=40)

    @field_validator("items")
    @classmethod
    def trim_items(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class ResumeContent(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=24)
    github_url: str | None = Field(default=None, max_length=500)
    linkedin_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    summary: str = Field(default="", max_length=900)
    skills: list[SkillText] = Field(default_factory=list, max_length=40)
    skill_groups: list[SkillGroup] = Field(default_factory=list, max_length=12)
    projects: list[ResumeEntry | ProjectText] = Field(default_factory=list, max_length=10)
    education: list[ResumeEntry | EducationText] = Field(default_factory=list, max_length=6)
    experience: list[ResumeEntry | ExperienceText] = Field(default_factory=list, max_length=10)
    credentials: list[CredentialText] = Field(default_factory=list, max_length=12)
    research: list[ResumeEntry | CredentialText] = Field(default_factory=list, max_length=10)
    publications: list[ResumeEntry | CredentialText] = Field(default_factory=list, max_length=10)
    certifications: list[ResumeEntry | CredentialText] = Field(default_factory=list, max_length=12)
    achievements: list[AchievementText] = Field(default_factory=list, max_length=12)
    positions: list[ResumeEntry | CredentialText] = Field(default_factory=list, max_length=10)
    extracurricular: list[ResumeEntry | CredentialText] = Field(default_factory=list, max_length=10)
    section_order: list[ResumeSection] = Field(
        default_factory=_default_section_order,
        max_length=10,
    )

    @field_validator("full_name", "email")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = str(value).strip()
        if not cleaned:
            raise ValueError("Required resume values cannot be blank")
        return cleaned

    @field_validator("summary")
    @classmethod
    def strip_summary(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def unique_section_order(self) -> "ResumeContent":
        if len(self.section_order) != len(set(self.section_order)):
            raise ValueError("section_order must not contain duplicate sections")
        return self


def suggestion_is_supported(proposed: str, known_facts: set[str]) -> bool:
    lowered = proposed.casefold()
    suspicious = {"increased", "reduced", "million", "award", "certified"}
    return not any(term in lowered and term not in known_facts for term in suspicious)


def evidence_digest(content: ResumeContent) -> str:
    canonical = json.dumps(
        content.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def generate_pdf(
    content: ResumeContent,
    *,
    artifact_id: str | None = None,
    settings: Settings | None = None,
) -> bytes:
    """Compile reviewed structured evidence using the versioned CampusHire LaTeX template."""
    from app.modules.resumes.latex_renderer import compile_resume_pdf

    return compile_resume_pdf(
        content,
        settings=settings or get_settings(),
        artifact_id=artifact_id,
    )
