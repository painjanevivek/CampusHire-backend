from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SemanticMatchResponse(BaseModel):
    status: Literal["available", "unavailable"]
    score: int | None
    components: dict[str, float]
    explanation: list[str]
    embedding_model: str
    embedding_version: str
    scoring_version: str
    source_resume_version_id: UUID | None
    source_profile_revision: int | None
    safe_error_code: str | None = None
    evaluated_at: datetime | None = None


class PolicySectionInput(BaseModel):
    section: str = Field(min_length=1, max_length=160)
    page: int = Field(ge=1, le=10_000)
    text: str = Field(min_length=1, max_length=8_000)


class PolicyCreate(BaseModel):
    title: str = Field(min_length=3, max_length=240)
    source_reference: str = Field(min_length=3, max_length=500)
    sections: list[PolicySectionInput] = Field(min_length=1, max_length=500)


class PolicyReview(BaseModel):
    action: Literal["approve", "reject", "retire"]
    reason: str = Field(min_length=10, max_length=500)


class PolicyResponse(BaseModel):
    id: UUID
    title: str
    version: int
    source_reference: str
    sections: list[dict[str, object]]
    status: str
    review_reason: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PolicyQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class PolicyAnswer(BaseModel):
    answer: str
    citations: list[str]
    policy_id: UUID | None
    policy_version: int | None
    grounded: bool


class ExtractionCreate(BaseModel):
    source_text: str = Field(min_length=20, max_length=20_000)


class ExtractionReview(BaseModel):
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=10, max_length=500)
    requirements: list[str] | None = Field(default=None, max_length=40)
    skills: list[str] | None = Field(default=None, max_length=40)

    @field_validator("requirements", "skills")
    @classmethod
    def unique_nonempty(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value if item.strip()]
        if len(cleaned) != len({item.casefold() for item in cleaned}):
            raise ValueError("Values must be unique")
        return cleaned


class ExtractionResponse(BaseModel):
    id: UUID
    role_id: UUID
    proposed_requirements: list[str]
    proposed_skills: list[str]
    provider_name: str
    model_version: str
    prompt_version: str
    status: str
    review_reason: str | None
    created_at: datetime
    updated_at: datetime
