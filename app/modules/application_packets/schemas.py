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


class CompensationTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    period: Literal["hourly", "monthly", "annual", "one_time"]
    minimum_amount: int = Field(ge=0)
    maximum_amount: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_range(self) -> "CompensationTerms":
        if self.maximum_amount is not None and self.maximum_amount < self.minimum_amount:
            raise ValueError("Maximum compensation must not be lower than minimum compensation")
        return self


class CommitmentTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool
    duration_months: int | None = Field(default=None, ge=1, le=120)
    penalty_amount: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    details: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def valid_commitment(self) -> "CommitmentTerms":
        if not self.required and any(
            value is not None
            for value in (self.duration_months, self.penalty_amount, self.currency, self.details)
        ):
            raise ValueError("Optional commitment details require required=true")
        if self.penalty_amount is not None and self.currency is None:
            raise ValueError("Penalty currency is required when a penalty amount is provided")
        return self


class MaterialTermsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compensation: CompensationTerms
    work_location: str = Field(min_length=2, max_length=200)
    work_mode: Literal["on-site", "hybrid", "remote"]
    bond: CommitmentTerms
    probation: CommitmentTerms
    training: CommitmentTerms
    application_deadline: datetime
    required_documents: list[str] = Field(default_factory=list, max_length=30)
    selection_stages: list[str] = Field(default_factory=list, min_length=1, max_length=20)
    placement_restrictions: list[str] = Field(default_factory=list, max_length=30)
    additional_terms: str | None = Field(default=None, max_length=5000)

    @field_validator("required_documents", "selection_stages", "placement_restrictions")
    @classmethod
    def normalized_unique_terms(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if any(len(item) > 500 for item in normalized):
            raise ValueError("Material term list entries must be at most 500 characters")
        if len({item.casefold() for item in normalized}) != len(normalized):
            raise ValueError("Material term list entries must be unique")
        return normalized


class MaterialTermsResponse(BaseModel):
    id: UUID
    role_id: UUID
    version: int
    status: str
    terms: MaterialTermsUpdate
    content_digest: str
    created_by_user_id: UUID
    approved_by_user_id: UUID | None
    effective_at: datetime | None
    published_at: datetime | None
    superseded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MaterialTermChange(BaseModel):
    path: str
    before: object | None
    after: object | None


class MaterialTermsComparisonResponse(BaseModel):
    role_id: UUID
    from_version: int
    to_version: int
    changes: list[MaterialTermChange]


class ApplicationAcknowledgmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_terms_version_id: UUID
    content_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    confirmation: Literal["I ACKNOWLEDGE THESE MATERIAL TERMS"]


class DraftMaterialTermsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


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
    acknowledgment: ApplicationAcknowledgmentInput | None = None


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
    material_terms: MaterialTermsResponse | None
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
