from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DisclosureQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    prompt: str = Field(min_length=5, max_length=500)
    type: Literal["single_select", "multi_select", "boolean"]
    options: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("options")
    @classmethod
    def normalize_options(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 120 for item in normalized):
            raise ValueError("Disclosure options must be at most 120 characters")
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("Disclosure options must be unique")
        if any(item.casefold() == "prefer not to answer" for item in normalized):
            raise ValueError("Prefer not to answer is added by CampusHire")
        return normalized

    @model_validator(mode="after")
    def valid_options_for_type(self) -> "DisclosureQuestion":
        if self.type == "boolean" and self.options:
            raise ValueError("Boolean disclosure questions cannot define options")
        if self.type != "boolean" and len(self.options) < 2:
            raise ValueError("Select disclosure questions require at least two options")
        return self


class ApplicationFormUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=10, max_length=500)
    compliance_owner: str = Field(min_length=2, max_length=160)
    retention_days: int = Field(ge=1, le=3650)
    questions: list[DisclosureQuestion] = Field(default_factory=list, max_length=20)

    @field_validator("questions")
    @classmethod
    def unique_question_ids(cls, value: list[DisclosureQuestion]) -> list[DisclosureQuestion]:
        ids = [item.id for item in value]
        if len(set(ids)) != len(ids):
            raise ValueError("Disclosure question IDs must be unique")
        return value


class ApplicationFormResponse(BaseModel):
    id: UUID
    role_id: UUID
    version: int
    status: str
    purpose: str
    compliance_owner: str
    retention_days: int
    questions: list[DisclosureQuestion]
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DraftResumeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    resume_version_id: UUID


class DraftProfileConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    profile_revision: int = Field(ge=1)


DisclosureAnswer = bool | str | list[str]


class DraftDisclosureUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    answers: dict[str, DisclosureAnswer] = Field(default_factory=dict, max_length=20)


class DraftSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    confirmation: Literal["I CONFIRM THIS APPLICATION IS ACCURATE"]


class DraftResumeSummary(BaseModel):
    id: UUID
    original_name: str
    version_number: int | None
    created_at: datetime
    parent_version_id: UUID | None = None


class ApplicationDraftResponse(BaseModel):
    id: UUID
    role_id: UUID
    role_title: str
    company_name: str
    deadline_at: datetime
    current_step: str
    revision: int
    expires_at: datetime
    last_saved_at: datetime
    profile_revision: int | None
    resume: DraftResumeSummary | None
    form: ApplicationFormResponse | None
    disclosure_answers: dict[str, DisclosureAnswer]
    disclosure_completed: bool
    submitted_application_id: UUID | None


class ApplicationReviewResponse(BaseModel):
    draft: ApplicationDraftResponse
    profile_snapshot: dict[str, object]
    immutable_notice: str


class ApplicationDisclosureResponse(BaseModel):
    application_id: UUID
    form: ApplicationFormResponse
    answers: dict[str, DisclosureAnswer]
    retention_until: datetime
