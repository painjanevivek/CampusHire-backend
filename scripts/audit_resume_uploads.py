import asyncio
import json

from sqlalchemy import func, select

from app.core.database import SessionFactory
from app.models.recruitment import Application
from app.models.resume import JobStatus, ResumeProcessingJob, ResumeSource, ResumeVersion


async def inspect() -> dict[str, int | bool]:
    async with SessionFactory() as db:
        uploaded_versions = int(
            await db.scalar(
                select(func.count(ResumeVersion.id)).where(
                    ResumeVersion.source == ResumeSource.UPLOAD.value
                )
            )
            or 0
        )
        referenced_versions = int(
            await db.scalar(
                select(func.count(Application.id))
                .join(ResumeVersion, ResumeVersion.id == Application.resume_version_id)
                .where(ResumeVersion.source == ResumeSource.UPLOAD.value)
            )
            or 0
        )
        nonterminal_jobs = int(
            await db.scalar(
                select(func.count(ResumeProcessingJob.id))
                .join(ResumeVersion, ResumeVersion.id == ResumeProcessingJob.resume_version_id)
                .where(
                    ResumeVersion.source == ResumeSource.UPLOAD.value,
                    ResumeProcessingJob.status.in_(
                        (
                            JobStatus.QUEUED.value,
                            JobStatus.PROCESSING.value,
                            JobStatus.CANCELLATION_REQUESTED.value,
                        )
                    ),
                )
            )
            or 0
        )
    return {
        "uploaded_versions": uploaded_versions,
        "application_references": referenced_versions,
        "nonterminal_processing_jobs": nonterminal_jobs,
        "legacy_pipeline_removable": uploaded_versions == 0 and nonterminal_jobs == 0,
    }


def main() -> None:
    print(json.dumps(asyncio.run(inspect()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
