from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

OutcomeType = Literal[
    "selection",
    "offer_issued",
    "offer_accepted",
    "offer_declined",
    "offer_rescinded",
    "joining_deferred",
    "joining",
    "no_show",
    "placement_confirmed",
    "internship",
    "ppo",
    "higher_studies",
    "approved_off_campus",
]


class OutcomeEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_type: OutcomeType
    outcome_state: Literal["provisional", "verified"]
    event_at: AwareDatetime
    source_type: str = Field(min_length=2, max_length=48)
    source_reference: str | None = Field(default=None, max_length=500)
    evidence_reference: str | None = Field(default=None, max_length=500)
    compensation_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    compensation_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    compensation_period: Literal["hour", "month", "year", "total"] | None = None
    stipend_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    joining_date: date | None = None
    joining_location: str | None = Field(default=None, max_length=200)
    next_update_owner: str | None = Field(default=None, max_length=160)
    next_update_due_at: AwareDatetime | None = None
    supersedes_event_id: UUID | None = None
    correction_reason: str | None = Field(default=None, min_length=10, max_length=1000)

    @model_validator(mode="after")
    def validate_linked_fields(self) -> "OutcomeEventCreate":
        if self.compensation_amount is not None and (
            self.compensation_currency is None or self.compensation_period is None
        ):
            raise ValueError("Compensation requires currency and period")
        if self.supersedes_event_id is not None and self.correction_reason is None:
            raise ValueError("A correction reason is required when superseding an event")
        if self.supersedes_event_id is None and self.correction_reason is not None:
            raise ValueError("A correction reason is only valid for a superseding event")
        return self


class OutcomeEventResponse(BaseModel):
    id: UUID
    institution_id: UUID
    application_id: UUID
    student_user_id: UUID
    event_type: OutcomeType
    outcome_state: Literal["provisional", "verified"]
    event_at: datetime
    source_type: str
    source_reference: str | None
    evidence_reference: str | None
    verified_by_user_id: UUID | None
    verified_at: datetime | None
    compensation_amount: Decimal | None
    compensation_currency: str | None
    compensation_period: str | None
    stipend_amount: Decimal | None
    joining_date: date | None
    joining_location: str | None
    next_update_owner: str | None
    next_update_due_at: datetime | None
    supersedes_event_id: UUID | None
    superseded_by_event_id: UUID | None = None
    correction_reason: str | None
    created_by_user_id: UUID
    created_at: datetime


class OutcomeTotals(BaseModel):
    provisional: dict[str, int] = Field(default_factory=dict)
    verified: dict[str, int] = Field(default_factory=dict)


class MetricDefinitionResponse(BaseModel):
    id: UUID
    code: str
    version: int
    status: str
    effective_at: datetime
    filters: dict[str, object]
    numerator: dict[str, object]
    denominator: dict[str, object]
    exclusions: list[dict[str, object]]
    evidence_requirements: list[str]
    approved_by_user_id: UUID | None
    approved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class MetricDefinitionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=3, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    effective_at: AwareDatetime
    filters: dict[str, object] = Field(default_factory=dict)
    numerator: dict[str, object]
    denominator: dict[str, object]
    exclusions: list[dict[str, object]] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(min_length=1, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class MetricDefinitionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_status: Literal["draft"] = "draft"
    reason: str = Field(min_length=10, max_length=1000)
