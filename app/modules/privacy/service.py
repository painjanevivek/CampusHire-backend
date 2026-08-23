from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditEvent, InstitutionMembership, Session, User
from app.models.engagement import InAppNotification, RoadmapProgress, StudentRoadmap
from app.models.intelligence import SemanticMatchEvidence
from app.models.privacy import DataDeletionRequest
from app.models.profile import StudentProfile
from app.models.recruitment import Application, EligibilityEvaluation, SavedOpportunity
from app.models.resume import (
    Resume,
    ResumeJobEvent,
    ResumeProcessingJob,
    ResumeSuggestion,
    ResumeVersion,
)
from app.modules.privacy.schemas import DataDeletionResponse
from app.modules.resumes.storage import ObjectStore, ObjectStoreError


class PrivacyError(RuntimeError):
    pass


async def request_student_deletion(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution_id: UUID | None,
    correlation_id: str | None,
    max_cleanup_attempts: int = 5,
) -> DataDeletionResponse:
    application_exists = await db.scalar(
        select(Application.id).where(Application.student_user_id == user_id).limit(1)
    )
    if application_exists is not None:
        raise PrivacyError("student_data_retention_hold")

    object_keys = list(
        (
            await db.scalars(
                select(ResumeVersion.storage_key).where(ResumeVersion.user_id == user_id)
            )
        ).all()
    )
    deletion_request = DataDeletionRequest(
        user_id=user_id,
        institution_id=institution_id,
        object_keys=object_keys,
        status="pending",
        max_attempts=max_cleanup_attempts,
    )
    db.add(deletion_request)
    await db.flush()

    roadmap_ids = select(StudentRoadmap.id).where(StudentRoadmap.student_user_id == user_id)
    version_ids = select(ResumeVersion.id).where(ResumeVersion.user_id == user_id)
    job_ids = select(ResumeProcessingJob.id).where(
        ResumeProcessingJob.resume_version_id.in_(version_ids)
    )
    await db.execute(
        delete(RoadmapProgress).where(RoadmapProgress.student_roadmap_id.in_(roadmap_ids))
    )
    await db.execute(delete(StudentRoadmap).where(StudentRoadmap.student_user_id == user_id))
    await db.execute(
        delete(InAppNotification).where(InAppNotification.recipient_user_id == user_id)
    )
    await db.execute(
        delete(SemanticMatchEvidence).where(
            SemanticMatchEvidence.student_user_id == user_id
        )
    )
    await db.execute(delete(SavedOpportunity).where(SavedOpportunity.student_user_id == user_id))
    await db.execute(
        delete(EligibilityEvaluation).where(
            EligibilityEvaluation.student_user_id == user_id
        )
    )
    await db.execute(
        delete(ResumeSuggestion).where(ResumeSuggestion.resume_version_id.in_(version_ids))
    )
    await db.execute(delete(ResumeJobEvent).where(ResumeJobEvent.job_id.in_(job_ids)))
    await db.execute(
        delete(ResumeProcessingJob).where(ResumeProcessingJob.resume_version_id.in_(version_ids))
    )
    await db.execute(delete(ResumeVersion).where(ResumeVersion.user_id == user_id))
    await db.execute(delete(Resume).where(Resume.user_id == user_id))
    await db.execute(delete(StudentProfile).where(StudentProfile.user_id == user_id))
    await db.execute(delete(InstitutionMembership).where(InstitutionMembership.user_id == user_id))
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.execute(
        insert(AuditEvent).values(
            actor_user_id=None,
            institution_id=institution_id,
            event_type="student_data.deletion_requested",
            resource_type="data_deletion_request",
            resource_id=str(deletion_request.id),
            outcome="success",
            reason="student_confirmed_deletion",
            correlation_id=correlation_id,
            details={"cleanup_status": "pending"},
            created_at=datetime.now(UTC),
        )
    )
    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return DataDeletionResponse(
        id=deletion_request.id,
        status="pending",
        requested_at=deletion_request.requested_at,
        message="Account records were removed; private-object cleanup is queued.",
    )


async def process_next_deletion_cleanup(
    db: AsyncSession, *, store: ObjectStore, lease_seconds: int = 300
) -> UUID | None:
    now = datetime.now(UTC)
    item = await db.scalar(
        select(DataDeletionRequest)
        .where(
            DataDeletionRequest.status.in_(("pending", "cleanup_pending", "processing")),
            DataDeletionRequest.available_at <= now,
            DataDeletionRequest.attempts < DataDeletionRequest.max_attempts,
        )
        .order_by(DataDeletionRequest.available_at, DataDeletionRequest.requested_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if item is None:
        return None
    item.status = "processing"
    item.available_at = now + timedelta(seconds=lease_seconds)
    await db.commit()
    try:
        for key in item.object_keys:
            store.delete(key)
        item.object_keys = []
        item.status = "completed"
        item.completed_at = datetime.now(UTC)
        item.available_at = item.completed_at
        item.safe_error_code = None
    except ObjectStoreError:
        item.attempts += 1
        if item.attempts >= item.max_attempts:
            item.status = "failed"
        else:
            item.status = "cleanup_pending"
            item.available_at = datetime.now(UTC) + timedelta(
                seconds=min(2**item.attempts, 300)
            )
        item.safe_error_code = "private_object_cleanup_unavailable"
    await db.commit()
    return item.id
