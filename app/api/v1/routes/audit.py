import csv
import io
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from app.modules.audit.schemas import AuditEventPage
from app.modules.audit.service import export_audit_events, list_audit_events, record_audit_event
from app.modules.auth.dependencies import CurrentPrincipal, Database, require_permissions

router = APIRouter(
    prefix="/admin/audit",
    dependencies=[Depends(require_permissions("audit.read"))],
)


def _institution(principal: CurrentPrincipal) -> UUID:
    if principal.institution_id is None:  # pragma: no cover - permission dependency fails first
        raise RuntimeError("institution membership required")
    return principal.institution_id


def _csv_cell(value: object | None) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


@router.get("/events", response_model=AuditEventPage)
async def read_audit_events(
    db: Database,
    principal: CurrentPrincipal,
    actor_user_id: UUID | None = None,
    resource_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    correlation_id: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    sort: Literal["asc", "desc"] = "desc",
) -> AuditEventPage:
    return await list_audit_events(
        db,
        _institution(principal),
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        action=action,
        outcome=outcome,
        correlation_id=correlation_id,
        start_at=start_at,
        end_at=end_at,
        page=page,
        page_size=page_size,
        sort=sort,
    )


@router.get(
    "/export.csv",
    dependencies=[Depends(require_permissions("audit.export"))],
)
async def download_audit_export(
    request: Request,
    db: Database,
    principal: CurrentPrincipal,
    actor_user_id: UUID | None = None,
    resource_type: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    correlation_id: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sort: Literal["asc", "desc"] = "desc",
) -> StreamingResponse:
    institution_id = _institution(principal)
    events = export_audit_events(
        db,
        institution_id,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        action=action,
        outcome=outcome,
        correlation_id=correlation_id,
        start_at=start_at,
        end_at=end_at,
        sort=sort,
    )
    async def stream_csv() -> AsyncIterator[str]:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "timestamp",
                "action",
                "outcome",
                "actor_user_id",
                "resource_type",
                "resource_id",
                "reason",
                "correlation_id",
            ]
        )
        yield output.getvalue()
        row_count = 0
        completed = False
        try:
            async for event in events:
                output.seek(0)
                output.truncate(0)
                writer.writerow(
                    [
                        _csv_cell(event.created_at.isoformat()),
                        _csv_cell(event.event_type),
                        _csv_cell(event.outcome),
                        _csv_cell(event.actor_user_id),
                        _csv_cell(event.resource_type),
                        _csv_cell(event.resource_id),
                        _csv_cell(event.reason),
                        _csv_cell(event.correlation_id),
                    ]
                )
                row_count += 1
                yield output.getvalue()
            completed = True
        finally:
            record_audit_event(
                db,
                event_type="audit.exported",
                actor_user_id=principal.user.id,
                institution_id=institution_id,
                resource_type="audit_event",
                outcome="success" if completed else "failure",
                reason=None if completed else "client_disconnected",
                correlation_id=request.state.correlation_id,
                details={"row_count": row_count},
            )
            await db.commit()

    return StreamingResponse(
        content=stream_csv(),
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="campushire-audit.csv"',
            "Cache-Control": "no-store",
        },
    )
