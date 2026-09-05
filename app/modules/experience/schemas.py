from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    instructions: str = Field(min_length=10, max_length=2000)
    deadline_at: AwareDatetime | None = None


class RequestResponseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    body: str = Field(min_length=10, max_length=4000)
    resume_version_id: UUID | None = None


class RequestResolution(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    action: Literal["resolve", "reopen", "cancel"]
    body: str = Field(min_length=10, max_length=2000)


class CorrectionEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID
    action: str
    body: str
    resume_version_id: UUID | None
    created_at: datetime


class CorrectionResponse(BaseModel):
    id: UUID
    application_id: UUID
    instructions: str
    deadline_at: datetime | None
    overdue: bool = False
    status: Literal["open", "awaiting_review", "resolved", "cancelled"]
    revision: int
    created_at: datetime
    updated_at: datetime
    events: list[CorrectionEventResponse] = Field(default_factory=list)


class ApplicationQueueItem(BaseModel):
    id: UUID
    student_name: str
    role_title: str
    company_name: str
    status: str
    revision: int
    created_at: datetime
    open_requests: int
    awaiting_review: int


class ApplicationQueuePage(BaseModel):
    items: list[ApplicationQueueItem]
    total: int
    page: int
    page_size: int


class SavedViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    filters: dict[str, str] = Field(default_factory=dict, max_length=10)

    @field_validator("filters")
    @classmethod
    def validate_filters(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {
            "q",
            "location",
            "work_mode",
            "skill",
            "eligibility",
            "application_state",
            "deadline_within_days",
            "saved_only",
            "sort",
        }
        if any(k not in allowed or len(v) > 120 for k, v in value.items()):
            raise ValueError("Only supported opportunity filters can be saved")
        enums = {
            "work_mode": {"on-site", "hybrid", "remote"},
            "sort": {"newest", "deadline", "company"},
            "eligibility": {"eligible", "ineligible", "needs_manual_review", "unavailable"},
            "saved_only": {"true", "false"},
            "application_state": {
                "submitted",
                "under_review",
                "shortlisted",
                "interview",
                "offered",
                "rejected",
                "withdrawn",
            },
        }
        if any(k in enums and v not in enums[k] for k, v in value.items() if v):
            raise ValueError("Unsupported filter value")
        days = value.get("deadline_within_days")
        if days and (not days.isdigit() or not 1 <= int(days) <= 90):
            raise ValueError("Deadline range must be between 1 and 90 days")
        return {k: v for k, v in value.items() if v}


class SavedViewResponse(SavedViewCreate):
    id: UUID


class Metric(BaseModel):
    key: str
    label: str
    value: float | None
    sample_size: int
    explanation: str
    href: str


class ReportResponse(BaseModel):
    start_at: datetime
    end_at: datetime
    timezone: str
    metrics: list[Metric]


class PreparationEvidence(BaseModel):
    requirement: str
    demonstrated: bool
    evidence: str


class PreparationResponse(BaseModel):
    role_id: UUID
    role_title: str
    source_resume_version_id: UUID | None
    source_profile_revision: int | None
    evidence: list[PreparationEvidence]
    requirements: list[str]
    mapping_status: str
    roadmap_href: str
    suggestions: list[dict[str, object]]
    guidance_stale: bool
    activities: list[dict[str, str]] = Field(default_factory=list)
