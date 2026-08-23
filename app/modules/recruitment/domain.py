from datetime import UTC, datetime
from enum import StrEnum


class DriveStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    OPEN = "open"
    CLOSED = "closed"
    SHORTLISTING = "shortlisting"
    INTERVIEW = "interview"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class ApplicationStatus(StrEnum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    SHORTLISTED = "shortlisted"
    INTERVIEW = "interview"
    OFFERED = "offered"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


TRANSITIONS = {
    ApplicationStatus.SUBMITTED: {ApplicationStatus.UNDER_REVIEW, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.UNDER_REVIEW: {ApplicationStatus.SHORTLISTED, ApplicationStatus.REJECTED},
    ApplicationStatus.SHORTLISTED: {ApplicationStatus.INTERVIEW, ApplicationStatus.REJECTED},
    ApplicationStatus.INTERVIEW: {ApplicationStatus.OFFERED, ApplicationStatus.REJECTED},
}


def can_apply(drive_status: DriveStatus, deadline: datetime, now: datetime | None = None) -> bool:
    current = now or datetime.now(UTC)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    return drive_status is DriveStatus.OPEN and current <= deadline


def validate_transition(current: ApplicationStatus, target: ApplicationStatus) -> None:
    if target not in TRANSITIONS.get(current, set()):
        raise ValueError(f"Cannot move application from {current} to {target}")
