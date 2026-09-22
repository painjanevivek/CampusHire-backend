from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataDeletionCreate(BaseModel):
    confirmation: Literal["DELETE MY CAMPUSHIRE DATA"]
    scope: Literal["account_all_memberships"]


class DataDeletionResponse(BaseModel):
    id: UUID
    status: str
    requested_at: datetime
    message: str


class PrivacyRequestCreate(BaseModel):
    request_type: Literal["export", "correction", "erasure", "consent_withdrawal", "grievance"]
    details: str | None = Field(default=None, max_length=2000)


class PrivacyRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None
    request_type: str
    status: str
    details: str | None
    owner_user_id: UUID | None
    due_at: datetime | None
    result_summary: str | None
    resolution_effect: str | None
    processing_receipt: dict[str, object]
    cleanup_request_id: UUID | None
    receipt_reference: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PrivacyRequestDecision(BaseModel):
    action: Literal["assign", "approve", "decline", "hold", "complete"]
    owner_user_id: UUID | None = None
    reason: str = Field(min_length=10, max_length=2000)
    resolution_effect: str | None = Field(default=None, min_length=3, max_length=80)
    expected_updated_at: datetime

    @model_validator(mode="after")
    def require_resolution_effect(self) -> "PrivacyRequestDecision":
        if self.action in {"approve", "decline", "complete"} and not self.resolution_effect:
            raise ValueError("A resolution effect is required for this action")
        return self


class LegalHoldCreate(BaseModel):
    user_id: UUID | None = None
    scope: dict[str, object]
    reason: str = Field(min_length=10, max_length=1000)
    owner_user_id: UUID
    review_at: datetime


class LegalHoldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution_id: UUID | None
    user_id: UUID | None
    scope: dict[str, object]
    reason: str
    owner_user_id: UUID
    review_at: datetime
    released_at: datetime | None
    release_reason: str | None
    created_at: datetime
    updated_at: datetime


class LegalHoldRelease(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)
    expected_updated_at: datetime
