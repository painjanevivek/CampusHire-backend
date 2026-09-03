from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EducationItem(BaseModel):
    degree: str = Field(min_length=2, max_length=120)
    branch: str = Field(min_length=2, max_length=120)
    institution: str = Field(min_length=2, max_length=200)
    start_year: int = Field(ge=1990, le=2100)
    graduation_year: int = Field(ge=1990, le=2100)
    score: float = Field(ge=0, le=100)
    score_scale: Literal["cgpa_10", "percentage"]


class SkillItem(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    proficiency: Literal["learning", "comfortable", "strong"]


class ProfileUpdate(BaseModel):
    expected_revision: int | None = Field(default=None, ge=1)
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    institution_name: str | None = Field(default=None, min_length=2, max_length=200)
    prn: str | None = Field(default=None, min_length=2, max_length=64)
    department: str | None = Field(default=None, min_length=2, max_length=120)
    academic_year: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{7,24}$")
    city: str | None = Field(default=None, min_length=2, max_length=120)
    country_code: str | None = Field(
        default=None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$"
    )
    education: list[EducationItem] | None = Field(default=None, max_length=6)
    skills: list[SkillItem] | None = Field(default=None, max_length=40)
    target_roles: list[str] | None = Field(default=None, min_length=1, max_length=5)
    github_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    onboarding_step: int | None = Field(default=None, ge=1, le=8)

    @field_validator("github_url")
    @classmethod
    def validate_github(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            raise ValueError("Use a complete HTTPS GitHub profile URL")
        return value

    @field_validator("portfolio_url")
    @classmethod
    def validate_portfolio(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Use a complete HTTPS portfolio URL")
        return value

    @field_validator("skills")
    @classmethod
    def unique_skills(cls, value: list[SkillItem] | None) -> list[SkillItem] | None:
        if value and len({item.name.strip().casefold() for item in value}) != len(value):
            raise ValueError("Each skill can be added only once")
        return value


class ReadinessItem(BaseModel):
    key: str
    label: str
    complete: bool
    required: bool


class ProfileResponse(BaseModel):
    id: UUID
    institution_id: UUID | None
    full_name: str | None
    institution_name: str | None
    prn: str | None
    department: str | None
    academic_year: str | None
    phone: str | None
    account_email: str | None = None
    city: str | None
    country_code: str | None
    education: list[dict[str, object]]
    skills: list[dict[str, object]]
    target_roles: list[str]
    external_links: dict[str, str]
    onboarding_step: int
    revision: int
    updated_at: datetime
    readiness: int
    is_complete: bool
    checklist: list[ReadinessItem]


class IdentityUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    institution_name: str | None = Field(default=None, min_length=2, max_length=200)
    prn: str | None = Field(default=None, min_length=2, max_length=64)
    department: str | None = Field(default=None, min_length=2, max_length=120)
    academic_year: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 ()-]{7,24}$")
    city: str | None = Field(default=None, min_length=2, max_length=120)
    country_code: str | None = Field(
        default=None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$"
    )
    onboarding_step: int | None = Field(default=None, ge=1, le=8)


class EducationUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    education: list[EducationItem] = Field(max_length=6)
    onboarding_step: int | None = Field(default=None, ge=1, le=8)


class SkillsUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    skills: list[SkillItem] = Field(max_length=40)
    onboarding_step: int | None = Field(default=None, ge=1, le=8)

    @field_validator("skills")
    @classmethod
    def unique_skills(cls, value: list[SkillItem]) -> list[SkillItem]:
        if len({item.name.strip().casefold() for item in value}) != len(value):
            raise ValueError("Each skill can be added only once")
        return value


class PreferencesUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    target_roles: list[str] = Field(min_length=1, max_length=5)
    onboarding_step: int | None = Field(default=None, ge=1, le=8)


class LinksUpdate(BaseModel):
    expected_revision: int = Field(ge=1)
    github_url: str | None = Field(default=None, max_length=500)
    portfolio_url: str | None = Field(default=None, max_length=500)
    onboarding_step: int | None = Field(default=None, ge=1, le=8)

    @field_validator("github_url")
    @classmethod
    def validate_github(cls, value: str | None) -> str | None:
        return ProfileUpdate.validate_github(value)

    @field_validator("portfolio_url")
    @classmethod
    def validate_portfolio(cls, value: str | None) -> str | None:
        return ProfileUpdate.validate_portfolio(value)
