from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditEvent


def record_audit_event(
    db: AsyncSession,
    *,
    event_type: str,
    actor_user_id: UUID | None = None,
    institution_id: UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: str = "success",
    reason: str | None = None,
    correlation_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Attach an audit event to the caller's transaction without committing it."""
    event = AuditEvent(
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        reason=reason,
        correlation_id=correlation_id,
        details=details or {},
    )
    db.add(event)
    return event
