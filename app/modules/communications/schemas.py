from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CommunicationPreferencesResponse(BaseModel):
    application_updates: bool
    deadline_reminders: bool
    security_emails: Literal[True] = True
    account_emails: Literal[True] = True


class CommunicationPreferencesUpdate(BaseModel):
    application_updates: bool
    deadline_reminders: bool


class EmailDeliveryResponse(BaseModel):
    id: UUID
    category: str
    template_key: str
    status: str
    attempts: int
    max_attempts: int
    safe_error_code: str | None
    next_attempt_at: datetime
    sent_at: datetime | None
    failed_at: datetime | None
    bounced_at: datetime | None
    created_at: datetime


class EmailDeliveryPage(BaseModel):
    items: list[EmailDeliveryResponse]
    total: int


class ServiceStatusResponse(BaseModel):
    status: Literal["operational", "maintenance"]
    maintenance_message: str | None
    transactional_email: Literal["configured", "degraded"]


class BounceEventCreate(BaseModel):
    provider_message_id: str = Field(min_length=1, max_length=200)


class SupportRequestCreate(BaseModel):
    category: Literal[
        "account",
        "profile",
        "eligibility",
        "application",
        "resume",
        "roadmap",
        "privacy",
        "accessibility",
        "other",
    ]
    route_context: str = Field(pattern=r"^/[a-z0-9/_-]{0,99}$")
    message: str = Field(min_length=20, max_length=1000)

    @field_validator("message")
    @classmethod
    def reject_personal_contact_details(cls, value: str) -> str:
        lowered = value.casefold()
        if "@" in value or "password" in lowered or "token" in lowered:
            raise ValueError("Do not include email addresses, passwords, or token values")
        if any(character.isdigit() for character in value) and sum(c.isdigit() for c in value) >= 7:
            raise ValueError("Do not include phone, enrollment, or other long numeric identifiers")
        return value.strip()


class SupportRequestResponse(BaseModel):
    reference: UUID
    status: str
    created_at: datetime


class FunnelMetric(BaseModel):
    event_name: str
    count: int


class FunnelResponse(BaseModel):
    metrics: list[FunnelMetric]
    window_days: int
