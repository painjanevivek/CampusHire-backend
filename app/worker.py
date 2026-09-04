import argparse
import asyncio
import logging
from uuid import uuid4

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.logging import configure_logging
from app.modules.application_packets.service import purge_expired_application_packet_data
from app.modules.communications.reminders import enqueue_upcoming_deadline_reminders
from app.modules.communications.service import OciSmtpEmailProvider, process_next_email
from app.modules.privacy.service import process_next_deletion_cleanup
from app.modules.resumes.parser import build_pdf_parser
from app.modules.resumes.pipeline import claim_next_job, process_job, recover_stale_jobs
from app.modules.resumes.scanner import build_scanner
from app.modules.resumes.storage import build_object_store

logger = logging.getLogger(__name__)


async def run_worker(*, once: bool = False, worker_id: str | None = None) -> None:
    settings = get_settings()
    if settings.process_role == "api":
        raise RuntimeError("The durable worker cannot run with PROCESS_ROLE=api")
    store = build_object_store(settings)
    scanner = build_scanner(settings)
    parser_backend = build_pdf_parser(settings)
    worker_identity = worker_id or f"resume-worker-{uuid4().hex[:12]}"
    logger.info(
        "resume_worker_started",
        extra={"event": "resume_worker_started", "worker_id": worker_identity},
    )
    next_reminder_sweep_at = 0.0
    next_application_packet_cleanup_at = 0.0
    while True:
        loop_time = asyncio.get_running_loop().time()
        if loop_time >= next_application_packet_cleanup_at:
            try:
                async with SessionFactory() as db:
                    disclosure_count, draft_count = await purge_expired_application_packet_data(db)
                    await db.commit()
                if disclosure_count or draft_count:
                    logger.info(
                        "application_packet_retention_enforced",
                        extra={
                            "event": "application_packet_retention_enforced",
                            "disclosure_count": disclosure_count,
                            "draft_count": draft_count,
                            "worker_id": worker_identity,
                        },
                    )
            except Exception:
                logger.exception(
                    "application_packet_cleanup_failed",
                    extra={
                        "event": "application_packet_cleanup_failed",
                        "worker_id": worker_identity,
                    },
                )
            next_application_packet_cleanup_at = (
                loop_time + settings.application_packet_cleanup_seconds
            )
        if settings.email_smtp_host:
            if loop_time >= next_reminder_sweep_at:
                try:
                    async with SessionFactory() as db:
                        reminder_count = await enqueue_upcoming_deadline_reminders(
                            db, settings=settings
                        )
                        await db.commit()
                    if reminder_count:
                        logger.info(
                            "deadline_reminders_queued",
                            extra={
                                "event": "deadline_reminders_queued",
                                "job_count": reminder_count,
                                "worker_id": worker_identity,
                            },
                        )
                except Exception:
                    logger.exception(
                        "deadline_reminder_sweep_failed",
                        extra={
                            "event": "deadline_reminder_sweep_failed",
                            "worker_id": worker_identity,
                        },
                    )
                next_reminder_sweep_at = loop_time + settings.email_reminder_sweep_seconds
            async with SessionFactory() as db:
                email_id = await process_next_email(db, OciSmtpEmailProvider(settings))
            if email_id is not None:
                logger.info(
                    "transactional_email_processed",
                    extra={"event": "transactional_email_processed", "resource_id": str(email_id)},
                )
                if once:
                    return
                continue
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
            await process_job(
                db,
                job_id,
                store=store,
                scanner=scanner,
                parser=parser_backend,
                settings=settings,
            )
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
