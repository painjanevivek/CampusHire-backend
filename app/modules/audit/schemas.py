from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    event_type: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    reason: str | None
    correlation_id: str | None
    details: dict[str, object]
    created_at: datetime


class AuditEventPage(BaseModel):
    items: list[AuditEventResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)
