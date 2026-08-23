import argparse
import asyncio
import logging
from uuid import uuid4

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import configure_logging
from app.modules.privacy.service import process_next_deletion_cleanup
from app.modules.resumes.pipeline import claim_next_job, process_job, recover_stale_jobs
from app.modules.resumes.scanner import build_scanner
from app.modules.resumes.storage import LocalObjectStore

logger = logging.getLogger(__name__)


async def run_worker(*, once: bool = False, worker_id: str | None = None) -> None:
    settings = get_settings()
    store = LocalObjectStore(settings.resume_storage_path)
    scanner = build_scanner(settings)
    worker_identity = worker_id or f"resume-worker-{uuid4().hex[:12]}"
    logger.info(
        "resume_worker_started",
        extra={"event": "resume_worker_started", "worker_id": worker_identity},
    )
    while True:
        async with SessionFactory() as db:
            deletion_id = await process_next_deletion_cleanup(
                db,
                store=store,
                lease_seconds=settings.privacy_cleanup_lease_seconds,
            )
        if deletion_id is not None:
            logger.info(
                "private_object_cleanup_processed",
                extra={
                    "event": "private_object_cleanup_processed",
                    "resource_id": str(deletion_id),
                    "worker_id": worker_identity,
                },
            )
            if once:
                return
            continue
        async with SessionFactory() as db:
            recovered = await recover_stale_jobs(
                db, stale_after_seconds=settings.resume_worker_lease_seconds
            )
            if recovered:
                logger.warning(
                    "resume_jobs_recovered",
                    extra={
                        "event": "resume_jobs_recovered",
                        "job_count": recovered,
                        "worker_id": worker_identity,
                    },
                )
            job_id = await claim_next_job(
                db,
                worker_id=worker_identity,
                lease_seconds=settings.resume_worker_lease_seconds,
            )
        if job_id is None:
            if once:
                return
            await asyncio.sleep(settings.resume_worker_poll_seconds)
            continue
        logger.info(
            "resume_job_claimed",
            extra={
                "event": "resume_job_claimed",
                "resource_id": str(job_id),
                "worker_id": worker_identity,
            },
        )
        async with SessionFactory() as db:
            await process_job(db, job_id, store=store, scanner=scanner, settings=settings)
        if once:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CampusHire background jobs")
    parser.add_argument("--once", action="store_true", help="Process at most one available job")
    args = parser.parse_args()
    configure_logging()
    asyncio.run(run_worker(once=args.once))


if __name__ == "__main__":
    main()
