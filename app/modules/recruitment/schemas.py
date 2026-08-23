from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.eligibility.engine import Rule

PublicationAction = Literal["publish", "close", "archive"]
ApplicationDecision = Literal[
    "under_review", "shortlisted", "interview", "offered", "rejected", "withdrawn"
]


class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website_url: str | None = Field(default=None, max_length=500, pattern=r"^https://")
    description: str | None = Field(default=None, max_length=4000)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    website_url: str | None = Field(default=None, max_length=500, pattern=r"^https://")
    description: str | None = Field(default=None, max_length=4000)


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    website_url: str | None
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class DriveCreate(BaseModel):
    company_id: UUID
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=8000)
    location: str = Field(min_length=2, max_length=160)
    work_mode: Literal["on-site", "hybrid", "remote"]
    opens_at: datetime
    deadline_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "DriveCreate":
        if self.opens_at >= self.deadline_at:
            raise ValueError("The application deadline must be after the opening time")
        return self


class DriveUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=8000)
    location: str | None = Field(default=None, min_length=2, max_length=160)
    work_mode: Literal["on-site", "hybrid", "remote"] | None = None
    opens_at: datetime | None = None
    deadline_at: datetime | None = None


class DriveResponse(BaseModel):
    id: UUID
    company_id: UUID
    company_name: str
    title: str
    description: str
    location: str
    work_mode: str
    opens_at: datetime
    deadline_at: datetime
    status: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    role_count: int = 0


class RoleCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=10, max_length=10000)
    employment_type: Literal["full-time", "internship", "contract"]
    location: str = Field(min_length=2, max_length=160)
    work_mode: Literal["on-site", "hybrid", "remote"]
    salary_display: str | None = Field(default=None, max_length=120)
    skills: list[str] = Field(default_factory=list, max_length=30)
    requirements: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("skills", "requirements")
    @classmethod
    def normalize_unique(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("Values must be unique")
        return normalized


class RoleUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, min_length=10, max_length=10000)
    employment_type: Literal["full-time", "internship", "contract"] | None = None
    location: str | None = Field(default=None, min_length=2, max_length=160)
    work_mode: Literal["on-site", "hybrid", "remote"] | None = None
    salary_display: str | None = Field(default=None, max_length=120)
    skills: list[str] | None = Field(default=None, max_length=30)
    requirements: list[str] | None = Field(default=None, max_length=30)


class RoleResponse(BaseModel):
    id: UUID
    drive_id: UUID
    company_name: str
    drive_title: str
    title: str
    description: str
    employment_type: str
    location: str
    work_mode: str
    salary_display: str | None
    skills: list[str]
    requirements: list[str]
    status: str
    published_at: datetime | None
    deadline_at: datetime


class RuleSetCreate(BaseModel):
    rules: list[Rule] = Field(min_length=1, max_length=40)


class RuleSetResponse(BaseModel):
    id: UUID
    role_id: UUID
    version: int
    status: str
    rules: list[dict[str, object]]
    created_by_user_id: UUID
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EligibilityResponse(BaseModel):
    status: Literal["eligible", "ineligible", "needs_manual_review", "unavailable"]
    rule_set_id: UUID | None
    rule_version: str | None
    results: list[dict[str, object]]
    missing_evidence: list[str]


class OpportunityResponse(RoleResponse):
    eligibility: EligibilityResponse
    saved: bool
    application_id: UUID | None = None
    application_status: str | None = None


class OpportunityPage(BaseModel):
    items: list[OpportunityResponse]
    page: int
    page_size: int
    total: int


class SaveResponse(BaseModel):
    role_id: UUID
    saved: bool


class ApplicationCreate(BaseModel):
    role_id: UUID
    resume_version_id: UUID


class StatusEventResponse(BaseModel):
    id: UUID
    from_status: str | None
    to_status: str
    actor_user_id: UUID
    reason: str | None
    created_at: datetime


class OverrideResponse(BaseModel):
    id: UUID
    actor_user_id: UUID
    previous_status: str
    target_status: str
    reason: str
    policy_reference: str | None
    created_at: datetime


class ApplicationResponse(BaseModel):
    id: UUID
    role_id: UUID
    student_user_id: UUID
    student_name: str
    student_email: str
    resume_version_id: UUID
    status: str
    role_snapshot: dict[str, object]
    resume_snapshot: dict[str, object]
    facts_snapshot: dict[str, object]
    rule_snapshot: dict[str, object]
    eligibility_snapshot: dict[str, object]
    created_at: datetime
    updated_at: datetime
    history: list[StatusEventResponse] = Field(default_factory=list)
    overrides: list[OverrideResponse] = Field(default_factory=list)


class AdminApplicationPage(BaseModel):
    items: list[ApplicationResponse]
    page: int
    page_size: int
    total: int


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationDecision
    reason: str | None = Field(default=None, max_length=500)


class ApplicationOverrideCreate(BaseModel):
    status: Literal["shortlisted", "rejected"]
    reason: str = Field(min_length=10, max_length=500)
    policy_reference: str | None = Field(default=None, max_length=300)
