from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ResumeJobEventResponse(BaseModel):
    id: UUID
    event_type: str
    status: str
    attempt: int
    worker_id: str | None
    safe_error_code: str | None
    correlation_id: str | None
    occurred_at: datetime


class ResumeJobOperatorResponse(BaseModel):
    id: UUID
    resume_version_id: UUID
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    started_at: datetime | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    claimed_by: str | None
    cancellation_requested_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    safe_error_code: str | None
    events: list[ResumeJobEventResponse] = Field(default_factory=list)


class ResumeJobPage(BaseModel):
    items: list[ResumeJobOperatorResponse]
    total: int


class OperationsSummaryResponse(BaseModel):
    status_counts: dict[str, int]
    oldest_queued_age_seconds: int | None
    active_leases: int
    exhausted_failures: int
