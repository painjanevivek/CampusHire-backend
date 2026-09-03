from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.resumes.builder import ResumeContent

ResumePipelineStage = Literal[
    "quarantined",
    "scanning",
    "scan_retry",
    "parsing",
    "parser_retry",
    "review",
    "generated",
    "ready",
    "failed",
    "cancelled",
]


class ResumeJobResponse(BaseModel):
    id: UUID
    status: str
    attempts: int
    max_attempts: int
    safe_error_code: str | None
    retryable: bool
    cancellable: bool
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    stage: ResumePipelineStage


class ResumeSuggestionResponse(BaseModel):
    id: UUID
    field_path: str
    original_text: str
    proposed_text: str
    rationale: str
    status: str
    decided_text: str | None


class ResumeVersionResponse(BaseModel):
    id: UUID
    version_number: int | None
    source: str
    original_name: str
    status: str
    scan_status: str
    page_count: int | None
    created_at: datetime
    review_completed_at: datetime | None
    review_revision: int
    evidence_digest: str
    generator_version: str | None
    processing_stage: ResumePipelineStage
    safe_error_code: str | None
    locked_by_application: bool = False
    parent_version_id: UUID | None = None
    purpose_role_id: UUID | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)
    job: ResumeJobResponse | None = None
    suggestions: list[ResumeSuggestionResponse] = Field(default_factory=list)


class ResumeUploadResponse(BaseModel):
    id: UUID
    version_number: int | None
    status: str
    scan_status: str
    duplicate: bool
    job_id: UUID | None


class TailoredResumeRequest(BaseModel):
    role_id: UUID
    content: ResumeContent


class ExtractionFieldDecision(BaseModel):
    field_path: str = Field(min_length=1, max_length=160)
    action: Literal["accept", "edit", "reject"]
    value: str | list[str] | None = None

    @model_validator(mode="after")
    def edited_value_is_required(self) -> "ExtractionFieldDecision":
        if self.action == "edit" and self.value is None:
            raise ValueError("Edited extraction decisions require a value")
        return self


class ExtractionReviewRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    decisions: list[ExtractionFieldDecision] = Field(min_length=1, max_length=50)


class SuggestionDecision(BaseModel):
    action: Literal["accept", "edit", "reject"]
    edited_text: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def edited_text_is_required(self) -> "SuggestionDecision":
        if self.action == "edit" and not self.edited_text:
            raise ValueError("Edited suggestions require text")
        if self.action != "edit" and self.edited_text is not None:
            raise ValueError("Edited text is only valid for edit decisions")
        return self


class SuggestionDecisionRequest(SuggestionDecision):
    expected_revision: int = Field(ge=0)


class SuggestionBatchItem(SuggestionDecision):
    suggestion_id: UUID


class SuggestionReviewBatch(BaseModel):
    expected_revision: int = Field(ge=0)
    decisions: list[SuggestionBatchItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def suggestion_ids_are_unique(self) -> "SuggestionReviewBatch":
        ids = [item.suggestion_id for item in self.decisions]
        if len(set(ids)) != len(ids):
            raise ValueError("Suggestion decisions must be unique")
        return self
