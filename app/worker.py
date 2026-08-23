import argparse
import asyncio
import logging

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import configure_logging
from app.modules.resumes.pipeline import claim_next_job, process_job, recover_stale_jobs
from app.modules.resumes.scanner import build_scanner
from app.modules.resumes.storage import LocalObjectStore

logger = logging.getLogger(__name__)


async def run_worker(*, once: bool = False) -> None:
    settings = get_settings()
    store = LocalObjectStore(settings.resume_storage_path)
    scanner = build_scanner(settings)
    while True:
        async with SessionFactory() as db:
            recovered = await recover_stale_jobs(db)
            if recovered:
                logger.warning("resume_jobs_recovered", extra={"count": recovered})
            job_id = await claim_next_job(db)
        if job_id is None:
            if once:
                return
            await asyncio.sleep(settings.resume_worker_poll_seconds)
            continue
        logger.info("resume_job_claimed", extra={"resource_id": str(job_id)})
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
