import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuditEvent, InstitutionMembership, Session, User
from app.models.engagement import InAppNotification, RoadmapProgress, StudentRoadmap
from app.models.intelligence import SemanticMatchEvidence
from app.models.privacy import DataDeletionRequest, LegalHold, PrivacyRequest
from app.models.profile import ProfilePhoto, StudentProfile
from app.models.recruitment import Application, EligibilityEvaluation, SavedOpportunity
from app.models.resume import (
    Resume,
    ResumeJobEvent,
    ResumeProcessingJob,
    ResumeSuggestion,
    ResumeVersion,
)
from app.modules.audit.service import record_audit_event
from app.modules.privacy.schemas import (
    DataDeletionResponse,
    LegalHoldCreate,
    LegalHoldRelease,
    LegalHoldResponse,
    PrivacyRequestCreate,
    PrivacyRequestDecision,
    PrivacyRequestResponse,
)
from app.modules.resumes.storage import ObjectStore, ObjectStoreError


class PrivacyError(RuntimeError):
    pass


async def list_legal_holds(
    db: AsyncSession, *, institution_id: UUID
) -> list[LegalHoldResponse]:
    items = (
        await db.scalars(
            select(LegalHold)
            .where(LegalHold.institution_id == institution_id)
            .order_by(LegalHold.released_at.is_(None).desc(), LegalHold.review_at, LegalHold.id)
        )
    ).all()
    return [LegalHoldResponse.model_validate(item) for item in items]


async def create_legal_hold(
    db: AsyncSession,
    *,
    institution_id: UUID,
    actor_user_id: UUID,
    payload: LegalHoldCreate,
    correlation_id: str | None,
) -> LegalHoldResponse:
    if payload.user_id is not None:
        membership = await db.scalar(
            select(InstitutionMembership.id).where(
                InstitutionMembership.institution_id == institution_id,
                InstitutionMembership.user_id == payload.user_id,
            )
        )
        if membership is None:
            raise PrivacyError("legal_hold_subject_not_in_institution")
    owner = await db.scalar(
        select(InstitutionMembership.id).where(
            InstitutionMembership.institution_id == institution_id,
            InstitutionMembership.user_id == payload.owner_user_id,
            InstitutionMembership.status == "active",
        )
    )
    if owner is None:
        raise PrivacyError("legal_hold_owner_not_active")
    item = LegalHold(
        institution_id=institution_id,
        user_id=payload.user_id,
        scope=payload.scope,
        reason=payload.reason,
        owner_user_id=payload.owner_user_id,
        review_at=payload.review_at,
    )
    db.add(item)
    await db.flush()
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="privacy.legal_hold.created",
        resource_type="legal_hold",
        resource_id=str(item.id),
        reason=payload.reason,
        correlation_id=correlation_id,
        details={"scope": payload.scope, "review_at": payload.review_at.isoformat()},
    )
    await db.commit()
    await db.refresh(item)
    return LegalHoldResponse.model_validate(item)


async def release_legal_hold(
    db: AsyncSession,
    *,
    institution_id: UUID,
    hold_id: UUID,
    actor_user_id: UUID,
    payload: LegalHoldRelease,
    correlation_id: str | None,
) -> LegalHoldResponse:
    item = await db.scalar(
        select(LegalHold)
        .where(LegalHold.id == hold_id, LegalHold.institution_id == institution_id)
        .with_for_update()
    )
    if item is None:
        raise PrivacyError("legal_hold_not_found")
    actual = (
        item.updated_at if item.updated_at.tzinfo else item.updated_at.replace(tzinfo=UTC)
    )
    expected = (
        payload.expected_updated_at
        if payload.expected_updated_at.tzinfo
        else payload.expected_updated_at.replace(tzinfo=UTC)
    )
    if actual != expected:
        raise PrivacyError("legal_hold_revision_conflict")
    if item.released_at is None:
        item.released_at = datetime.now(UTC)
        item.released_by_user_id = actor_user_id
        item.release_reason = payload.reason
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="privacy.legal_hold.released",
        resource_type="legal_hold",
        resource_id=str(item.id),
        reason=payload.reason,
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(item)
    return LegalHoldResponse.model_validate(item)


async def create_privacy_request(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution_id: UUID | None,
    payload: PrivacyRequestCreate,
    correlation_id: str | None,
) -> PrivacyRequestResponse:
    active = await db.scalar(
        select(PrivacyRequest.id).where(
            PrivacyRequest.user_id == user_id,
            PrivacyRequest.request_type == payload.request_type,
            PrivacyRequest.status.in_(("submitted", "assigned", "approved", "processing", "held")),
        )
    )
    if active is not None:
        raise PrivacyError("privacy_request_already_active")
    item = PrivacyRequest(
        user_id=user_id,
        subject_reference=hashlib.sha256(str(user_id).encode()).hexdigest(),
        institution_id=institution_id,
        request_type=payload.request_type,
        details=payload.details,
        due_at=datetime.now(UTC) + timedelta(days=7),
        receipt_reference=f"PR-{uuid4().hex[:16].upper()}",
    )
    db.add(item)
    await db.flush()
    record_audit_event(
        db,
        actor_user_id=user_id,
        institution_id=institution_id,
        event_type="privacy.request.submitted",
        resource_type="privacy_request",
        resource_id=str(item.id),
        correlation_id=correlation_id,
        details={"request_type": payload.request_type},
    )
    await db.commit()
    await db.refresh(item)
    return PrivacyRequestResponse.model_validate(item)


async def list_own_privacy_requests(
    db: AsyncSession, *, user_id: UUID
) -> list[PrivacyRequestResponse]:
    items = (
        await db.scalars(
            select(PrivacyRequest)
            .where(PrivacyRequest.user_id == user_id)
            .order_by(PrivacyRequest.created_at.desc(), PrivacyRequest.id)
        )
    ).all()
    return [PrivacyRequestResponse.model_validate(item) for item in items]


async def list_institution_privacy_requests(
    db: AsyncSession, *, institution_id: UUID
) -> list[PrivacyRequestResponse]:
    items = (
        await db.scalars(
            select(PrivacyRequest)
            .where(PrivacyRequest.institution_id == institution_id)
            .order_by(PrivacyRequest.created_at.desc(), PrivacyRequest.id)
            .limit(200)
        )
    ).all()
    return [PrivacyRequestResponse.model_validate(item) for item in items]


async def decide_privacy_request(
    db: AsyncSession,
    *,
    request_id: UUID,
    institution_id: UUID,
    actor_user_id: UUID,
    payload: PrivacyRequestDecision,
    correlation_id: str | None,
    max_cleanup_attempts: int,
) -> PrivacyRequestResponse:
    item = await db.scalar(
        select(PrivacyRequest)
        .where(
            PrivacyRequest.id == request_id,
            PrivacyRequest.institution_id == institution_id,
        )
        .with_for_update()
    )
    if item is None:
        raise PrivacyError("privacy_request_not_found")
    actual = item.updated_at if item.updated_at.tzinfo else item.updated_at.replace(tzinfo=UTC)
    expected = (
        payload.expected_updated_at
        if payload.expected_updated_at.tzinfo
        else payload.expected_updated_at.replace(tzinfo=UTC)
    )
    if actual != expected:
        raise PrivacyError("privacy_request_revision_conflict")
    if payload.action == "assign":
        if payload.owner_user_id is None:
            raise PrivacyError("privacy_request_owner_required")
        item.owner_user_id = payload.owner_user_id
        item.status = "assigned"
    elif payload.action == "decline":
        item.status = "declined"
        item.result_summary = payload.reason
        item.completed_at = datetime.now(UTC)
    elif payload.action == "hold":
        if item.user_id is None:
            raise PrivacyError("privacy_request_subject_unavailable")
        active_hold = await db.scalar(
            select(LegalHold.id).where(
                LegalHold.institution_id == institution_id,
                LegalHold.user_id == item.user_id,
                LegalHold.released_at.is_(None),
            )
        )
        if active_hold is None:
            raise PrivacyError("privacy_request_active_hold_required")
        item.status = "held"
        item.result_summary = payload.reason
    elif payload.action in {"approve", "complete"}:
        if item.request_type == "erasure" and item.user_id is not None:
            hold = await db.scalar(
                select(LegalHold.id).where(
                    LegalHold.user_id == item.user_id,
                    LegalHold.released_at.is_(None),
                )
            )
            if hold is not None:
                item.status = "held"
                item.result_summary = "Processing is paused by an active retention hold."
            else:
                try:
                    deletion = await request_student_deletion(
                        db,
                        user_id=item.user_id,
                        institution_id=item.institution_id,
                        correlation_id=correlation_id,
                        account_wide=True,
                        max_cleanup_attempts=max_cleanup_attempts,
                    )
                except PrivacyError as exc:
                    if str(exc) != "student_data_retention_hold":
                        raise
                    item.status = "held"
                    item.result_summary = (
                        "Processing is paused because placement records must be retained."
                    )
                    deletion = None
                if deletion is None:
                    record_audit_event(
                        db,
                        actor_user_id=actor_user_id,
                        institution_id=institution_id,
                        event_type="privacy.request.held",
                        resource_type="privacy_request",
                        resource_id=str(item.id),
                        reason="placement_record_retention",
                        correlation_id=correlation_id,
                    )
                    await db.commit()
                    await db.refresh(item)
                    return PrivacyRequestResponse.model_validate(item)
                await db.execute(
                    update(PrivacyRequest)
                    .where(PrivacyRequest.id == request_id)
                    .values(
                        status="processing",
                        cleanup_request_id=deletion.id,
                        result_summary=deletion.message,
                    )
                )
                await db.commit()
                refreshed = await db.get(PrivacyRequest, request_id)
                if refreshed is None:
                    raise PrivacyError("privacy_request_not_found")
                return PrivacyRequestResponse.model_validate(refreshed)
        else:
            item.status = "completed"
            item.result_summary = payload.reason
            item.completed_at = datetime.now(UTC)
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type=f"privacy.request.{item.status}",
        resource_type="privacy_request",
        resource_id=str(item.id),
        reason=payload.reason,
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(item)
    return PrivacyRequestResponse.model_validate(item)


async def request_student_deletion(
    db: AsyncSession,
    *,
    user_id: UUID,
    institution_id: UUID | None,
    correlation_id: str | None,
    account_wide: bool,
    max_cleanup_attempts: int = 5,
) -> DataDeletionResponse:
    if not account_wide:
        raise PrivacyError("account_wide_confirmation_required")
    affected_institutions = list(
        (
            await db.scalars(
                select(InstitutionMembership.institution_id).where(
                    InstitutionMembership.user_id == user_id
                )
            )
        ).all()
    )
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
    await db.execute(delete(ProfilePhoto).where(ProfilePhoto.user_id == user_id))
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
        delete(SemanticMatchEvidence).where(SemanticMatchEvidence.student_user_id == user_id)
    )
    await db.execute(delete(SavedOpportunity).where(SavedOpportunity.student_user_id == user_id))
    await db.execute(
        delete(EligibilityEvaluation).where(EligibilityEvaluation.student_user_id == user_id)
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
            details={
                "cleanup_status": "pending",
                "deletion_scope": "account_all_memberships",
                "affected_institution_count": len(affected_institutions),
            },
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
            item.available_at = datetime.now(UTC) + timedelta(seconds=min(2**item.attempts, 300))
        item.safe_error_code = "private_object_cleanup_unavailable"
    linked_request = await db.scalar(
        select(PrivacyRequest).where(PrivacyRequest.cleanup_request_id == item.id).with_for_update()
    )
    if linked_request is not None:
        if item.status == "completed":
            linked_request.status = "completed"
            linked_request.completed_at = item.completed_at
            linked_request.result_summary = "Erasure processing completed."
        elif item.status == "failed":
            linked_request.status = "failed"
            linked_request.result_summary = (
                "Account records were removed, but private-file cleanup needs support."
            )
    await db.commit()
    return item.id
