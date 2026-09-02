from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.notifications.domain import safe_deep_link


class RoadmapTemplateResponse(BaseModel):
    id: UUID
    slug: str
    title: str
    version: int
    summary: str
    node_count: int


class RoadmapNodeResponse(BaseModel):
    key: str
    title: str
    completion: str
    prerequisites: list[str]
    state: Literal["completed", "next", "locked"]
    evidence: dict[str, object]


class RoadmapResponse(BaseModel):
    id: UUID
    template_id: UUID
    slug: str
    title: str
    version: int
    summary: str
    completed_count: int
    nodes: list[RoadmapNodeResponse]


class RoadmapSelection(BaseModel):
    template_id: UUID


class RoadmapAvailabilityResponse(BaseModel):
    status: Literal[
        "available", "no_target_role", "no_approved_template", "institution_restriction"
    ]
    reason: str
    guidance_provider_status: Literal["available", "unavailable"]
    templates: list[RoadmapTemplateResponse]


class RoadmapProgressUpdate(BaseModel):
    completed: bool
    evidence_label: str | None = Field(default=None, max_length=160)
    evidence_reference: str | None = Field(default=None, max_length=500)

    @field_validator("evidence_reference")
    @classmethod
    def validate_reference(cls, value: str | None) -> str | None:
        if not value:
            return None
        return safe_deep_link(value)


class NextAction(BaseModel):
    key: str
    title: str
    description: str
    reason: str
    href: str
    policy_version: str
    source_facts: list[str]
    estimated_minutes: int = Field(ge=1, le=120)
    unlocks: str
    completion_criteria: str


class ActivationStage(BaseModel):
    key: Literal[
        "account_activated",
        "profile_minimum",
        "target_role",
        "resume_reviewed",
        "opportunities_unlocked",
        "first_application",
    ]
    label: str
    status: Literal["complete", "current", "upcoming"]
    href: str
    estimated_minutes: int = Field(ge=1, le=120)
    unlocks: str


class DashboardEvidence(BaseModel):
    label: str
    value: str
    status: Literal["verified", "pending", "review"]


class DashboardReadinessSummary(BaseModel):
    policy_version: str
    completed_evidence: int = Field(ge=0)
    total_evidence: int = Field(ge=1)
    required_complete: bool


class DashboardOpportunity(BaseModel):
    id: UUID
    company: str
    role: str
    location: str
    eligibility: str
    match: int | None
    href: str


class DashboardResponse(BaseModel):
    student_name: str
    readiness: DashboardReadinessSummary
    state: Literal["ready", "incomplete", "processing", "manual-review", "ai-unavailable"]
    next_action: NextAction
    activation: list[ActivationStage]
    evidence: list[DashboardEvidence]
    opportunities: list[DashboardOpportunity]
    roadmap: RoadmapResponse | None
    unread_notifications: int


class NotificationCreate(BaseModel):
    recipient_user_id: UUID
    event_key: str = Field(min_length=3, max_length=180, pattern=r"^[a-zA-Z0-9_.:-]+$")
    title: str = Field(min_length=3, max_length=180)
    body: str = Field(min_length=3, max_length=2_000)
    deep_link: str = Field(min_length=1, max_length=500)

    @field_validator("deep_link")
    @classmethod
    def local_link(cls, value: str) -> str:
        return safe_deep_link(value)


class NotificationResponse(BaseModel):
    id: UUID
    event_key: str
    title: str
    body: str
    deep_link: str
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    unread_count: int
