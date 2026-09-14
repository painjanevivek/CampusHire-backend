from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import StructuredGenerator
from app.ai.workflows.campus_agent import process_agent_run
from app.core.config import Settings
from app.models.agentic import AgentRun
from app.modules.agentic.service import _append_event


async def recover_stale_agent_runs(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    stale_runs = list(
        (
            await db.scalars(
                select(AgentRun)
                .where(
                    AgentRun.status == "running",
                    AgentRun.lease_expires_at < now,
                    AgentRun.cancel_requested.is_(False),
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for run in stale_runs:
        run.status = "queued"
        run.lease_owner = None
        run.lease_expires_at = None
        run.revision += 1
        await _append_event(
            db,
            run,
            "recovered",
            "Interrupted worker lease expired; task queued for safe recovery.",
        )
    await db.execute(
        update(AgentRun)
        .where(
            AgentRun.status == "running",
            AgentRun.lease_expires_at < now,
            AgentRun.cancel_requested.is_(False),
        )
        .values(status="queued", lease_owner=None, lease_expires_at=None)
    )
    await db.execute(
        update(AgentRun)
        .where(
            AgentRun.expires_at < now,
            AgentRun.status.in_(["queued", "awaiting_input"]),
        )
        .values(status="expired", required_action=None, lease_owner=None, lease_expires_at=None)
    )
    await db.commit()
    return len(stale_runs)


async def claim_next_agent_run(
    db: AsyncSession, *, worker_id: str, lease_seconds: int
) -> UUID | None:
    run = await db.scalar(
        select(AgentRun)
        .where(AgentRun.status == "queued", AgentRun.cancel_requested.is_(False))
        .order_by(AgentRun.created_at, AgentRun.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if run is None:
        return None
    run.status = "running"
    run.lease_owner = worker_id
    run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    run.revision += 1
    await _append_event(db, run, "running", "Bounded preparation task started.")
    await db.commit()
    return run.id


async def process_next_agent_run(
    db: AsyncSession,
    *,
    worker_id: str,
    generator: StructuredGenerator | None,
    settings: Settings,
) -> UUID | None:
    await recover_stale_agent_runs(db)
    run_id = await claim_next_agent_run(
        db, worker_id=worker_id, lease_seconds=settings.agent_worker_lease_seconds
    )
    if run_id is None:
        return None
    await process_agent_run(
        db,
        run_id,
        generator=generator,
        settings=settings,
        lease_owner=worker_id,
    )
    run = await db.get(AgentRun, run_id)
    if run is not None:
        run.lease_owner = None
        run.lease_expires_at = None
        await db.commit()
    return run_id
