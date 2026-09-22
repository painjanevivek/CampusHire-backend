from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


RunStatus = Literal[
    "queued", "running", "awaiting_input", "awaiting_review", "completed",
    "failed", "cancelled", "expired",
]


class StudentRunCreate(StrictModel):
    role_id: UUID
    goal: str = Field(min_length=3, max_length=500)
    available_minutes_per_week: int = Field(ge=30, le=10_080)
    target_date: date
    existing_plan_id: UUID | None = None


class TnpRunCreate(StrictModel):
    drive_id: UUID
    expected_revision: int = Field(ge=1)
    recruiter_brief: str | None = Field(default=None, min_length=20, max_length=20_000)
    source_version_ids: list[UUID] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_source(self) -> "TnpRunCreate":
        if not self.recruiter_brief and not self.source_version_ids:
            raise ValueError("Provide recruiter brief text or an authorized source reference")
        return self


class RunResume(StrictModel):
    expected_revision: int = Field(ge=1)
    interrupt_id: str = Field(min_length=4, max_length=120)
    response: str = Field(min_length=1, max_length=2_000)


class RunCancel(StrictModel):
    expected_revision: int = Field(ge=1)


class AgentEventResponse(StrictModel):
    sequence: int
    event_type: str
    summary: str
    metadata: dict[str, Any]
    created_at: datetime


class RunLimits(StrictModel):
    model_calls_remaining: int
    tool_calls_remaining: int
    correction_attempts_remaining: int
    active_seconds_remaining: float
    reserved_cost_microunits: int
    actual_cost_microunits: int


class AgentRunResponse(StrictModel):
    id: UUID
    audience: Literal["student", "tnp"]
    workflow: Literal["prepare_opportunity", "prepare_drive"]
    workflow_version: str
    source_projection_version: str
    evaluation_run_id: str | None
    provider_name: str
    model_version: str
    target_kind: Literal["role", "drive"]
    target_id: UUID
    status: RunStatus
    revision: int
    source_fingerprint: str | None
    limits: RunLimits
    required_action: dict[str, Any] | None
    safe_error: str | None
    artifact: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class EvidenceReference(StrictModel):
    source_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=300)
    access_scope: str = Field(min_length=1, max_length=80)


class EligibilitySummary(StrictModel):
    status: Literal["eligible", "ineligible", "needs_manual_review", "unavailable"]
    rule_version: str | None = None
    reasons: list[str] = Field(default_factory=list, max_length=20)
    missing_evidence: list[str] = Field(default_factory=list, max_length=20)


class PreparationActivity(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    objective: str = Field(min_length=5, max_length=500)
    minutes: int = Field(ge=10, le=1_200)
    due_offset_days: int = Field(ge=0, le=365)
    resource_source_ids: list[str] = Field(default_factory=list, max_length=8)


class PreparationPriority(StrictModel):
    skill: str = Field(min_length=1, max_length=120)
    evidence_state: Literal["recorded", "unknown", "assessed"]
    rationale: str = Field(min_length=5, max_length=600)
    source_ids: list[str] = Field(min_length=1, max_length=8)
    activities: list[PreparationActivity] = Field(min_length=1, max_length=6)


class PreparationPlanContent(StrictModel):
    title: str = Field(min_length=3, max_length=160)
    summary: str = Field(min_length=10, max_length=1_000)
    eligibility: EligibilitySummary
    priorities: list[PreparationPriority] = Field(min_length=1, max_length=8)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=12)
    total_minutes: int = Field(ge=10, le=100_000)
    limitations: list[str] = Field(default_factory=list, max_length=10)


class DriveFieldProposal(StrictModel):
    field: Literal["title", "description", "location", "work_mode", "opens_at", "deadline_at"]
    proposed_value: str = Field(min_length=1, max_length=8_000)
    rationale: str = Field(min_length=5, max_length=600)
    source_ids: list[str] = Field(min_length=1, max_length=8)


class DriveBlocker(StrictModel):
    key: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9_-]+$")
    description: str = Field(min_length=5, max_length=500)
    owner_role: Literal["recruiter", "tnp", "student", "institution"]
    status: Literal["proposed", "open", "resolved"] = "proposed"
    next_action: str = Field(min_length=5, max_length=500)
    deadline: date | None = None
    source_ids: list[str] = Field(default_factory=list, max_length=8)


class DrivePreparationContent(StrictModel):
    field_proposals: list[DriveFieldProposal] = Field(default_factory=list, max_length=12)
    clarification_questions: list[str] = Field(default_factory=list, max_length=20)
    announcement_draft: str = Field(min_length=10, max_length=5_000)
    blockers: list[DriveBlocker] = Field(default_factory=list, max_length=20)
    unresolved_work: list[str] = Field(default_factory=list, max_length=20)


class PlannerDecision(StrictModel):
    action: Literal["draft_artifact", "request_clarification"]
    reason: str = Field(min_length=5, max_length=300)
    clarification_question: str | None = Field(default=None, max_length=500)


class ArtifactEdit(StrictModel):
    expected_revision: int = Field(ge=1)
    content: dict[str, Any]


class ArtifactDecision(StrictModel):
    expected_revision: int = Field(ge=1)
    decision: Literal["accept", "reject"]


class ArtifactApply(StrictModel):
    expected_revision: int = Field(ge=1)
    expected_drive_revision: int = Field(ge=1)
    fields: list[
        Literal["title", "description", "location", "work_mode", "opens_at", "deadline_at"]
    ] = Field(min_length=1, max_length=6)


class ArtifactResponse(StrictModel):
    id: UUID
    run_id: UUID
    kind: Literal["preparation_plan", "drive_preparation"]
    target_id: UUID
    status: Literal["draft", "accepted", "rejected", "applied"]
    revision: int
    content: dict[str, Any]
    evidence_references: list[dict[str, Any]]
    source_fingerprint: str
    provider_name: str
    model_version: str
    workflow_version: str
    source_projection_version: str
    evaluation_run_id: str | None
    source_target_revision: int | None = None
    created_at: datetime
    updated_at: datetime


class PracticeConsentUpdate(StrictModel):
    consent_version: str = Field(min_length=1, max_length=40)
    opted_in: bool


class PracticeConsentResponse(StrictModel):
    purpose: Literal["practice_aggregates"]
    consent_version: str
    opted_in: bool
    granted_at: datetime | None
    revoked_at: datetime | None


class SourceVersionCreate(StrictModel):
    source_type: Literal["nptel", "swayam", "official_career_page", "faculty_resource"]
    canonical_url: str = Field(pattern=r"^https://", max_length=1_000)
    title: str = Field(min_length=2, max_length=300)
    permitted_use: str = Field(min_length=3, max_length=240)


class SourceReview(StrictModel):
    expected_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]


class SourceVersionResponse(StrictModel):
    id: UUID
    source_type: str
    canonical_url: str
    title: str
    version: int
    review_status: str
    access_scope: str
    permitted_use: str
    metadata: dict[str, Any]
    last_verified_at: datetime | None
    safe_error: str | None
    active: bool


class EscoSkill(StrictModel):
    uri: str
    preferred_label: str
    description: str | None = None
