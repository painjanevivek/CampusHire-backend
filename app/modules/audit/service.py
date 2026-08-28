from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.auth import AuditEvent
from app.modules.audit.schemas import AuditEventPage, AuditEventResponse

_SENSITIVE_DETAIL_MARKERS = {
    "content",
    "email",
    "password",
    "resume",
    "secret",
    "token",
}


def _safe_details(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in details.items():
        normalized = key.casefold()
        if any(marker in normalized for marker in _SENSITIVE_DETAIL_MARKERS):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[key[:100]] = value[:500] if isinstance(value, str) else value
    return sanitized


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
        details=_safe_details(details),
    )
    db.add(event)
    return event


def _audit_filters(
    institution_id: UUID,
    *,
    actor_user_id: UUID | None = None,
    resource_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    correlation_id: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = [AuditEvent.institution_id == institution_id]
    if actor_user_id:
        filters.append(AuditEvent.actor_user_id == actor_user_id)
    if resource_type:
        filters.append(AuditEvent.resource_type == resource_type)
    if action:
        filters.append(AuditEvent.event_type == action)
    if outcome:
        filters.append(AuditEvent.outcome == outcome)
    if correlation_id:
        filters.append(AuditEvent.correlation_id == correlation_id)
    if start_at:
        filters.append(AuditEvent.created_at >= start_at)
    if end_at:
        filters.append(AuditEvent.created_at <= end_at)
    return filters


def audit_response(event: AuditEvent) -> AuditEventResponse:
    return AuditEventResponse(
        id=event.id,
        actor_user_id=event.actor_user_id,
        event_type=event.event_type,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        outcome=event.outcome,
        reason=event.reason,
        correlation_id=event.correlation_id,
        details=dict(event.details),
        created_at=event.created_at,
    )


async def list_audit_events(
    db: AsyncSession,
    institution_id: UUID,
    *,
    actor_user_id: UUID | None = None,
    resource_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    correlation_id: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
    sort: Literal["asc", "desc"] = "desc",
) -> AuditEventPage:
    filters = _audit_filters(
        institution_id,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        action=action,
        outcome=outcome,
        correlation_id=correlation_id,
        start_at=start_at,
        end_at=end_at,
    )
    total = await db.scalar(select(func.count()).select_from(AuditEvent).where(*filters)) or 0
    order = AuditEvent.created_at.asc() if sort == "asc" else AuditEvent.created_at.desc()
    events = (
        await db.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(order, AuditEvent.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AuditEventPage(
        items=[audit_response(event) for event in events],
        page=page,
        page_size=page_size,
        total=total,
    )


async def export_audit_events(
    db: AsyncSession,
    institution_id: UUID,
    **filters: Any,
) -> list[AuditEventResponse]:
    page = await list_audit_events(
        db,
        institution_id,
        page=1,
        page_size=100,
        **filters,
    )
    return page.items
