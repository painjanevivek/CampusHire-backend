from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.profile import StudentProfile
from app.models.recruitment import (
    Application,
    ApplicationDisclosure,
    ApplicationDisclosureDraft,
    ApplicationDraft,
    Company,
    PlacementDrive,
    PlacementRole,
    PublicationStatus,
    RoleApplicationForm,
)
from app.models.resume import ResumeStatus, ResumeVersion, ScanStatus
from app.modules.application_packets.schemas import (
    ApplicationDisclosureResponse,
    ApplicationDraftResponse,
    ApplicationFormResponse,
    ApplicationFormUpdate,
    ApplicationReviewResponse,
    DisclosureAnswer,
    DisclosureQuestion,
    DraftResumeSummary,
)
from app.modules.auth.security import decrypt_sensitive_payload, encrypt_sensitive_payload
from app.modules.recruitment.schemas import ApplicationCreate
from app.modules.recruitment.service import create_application


class ApplicationPacketError(ValueError):
    pass


_DISCLOSURE_ANSWERS = TypeAdapter(dict[str, DisclosureAnswer])


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _institution(institution_id: UUID | None) -> UUID:
    if institution_id is None:
        raise ApplicationPacketError("institution_context_required")
    return institution_id


def form_response(form: RoleApplicationForm) -> ApplicationFormResponse:
    return ApplicationFormResponse(
        id=form.id,
        role_id=form.role_id,
        version=form.version,
        status=form.status,
        purpose=form.purpose,
        compliance_owner=form.compliance_owner,
        retention_days=form.retention_days,
        questions=[DisclosureQuestion.model_validate(item) for item in form.questions],
        published_at=form.published_at,
        created_at=form.created_at,
        updated_at=form.updated_at,
    )


async def _owned_role(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID
) -> PlacementRole:
    role = await db.scalar(
        select(PlacementRole).where(
            PlacementRole.id == role_id,
            PlacementRole.institution_id == _institution(institution_id),
        )
    )
    if role is None:
        raise ApplicationPacketError("role_not_found")
    return role


async def get_application_form(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID
) -> ApplicationFormResponse | None:
    await _owned_role(db, institution_id, role_id)
    form = await db.scalar(
        select(RoleApplicationForm)
        .where(RoleApplicationForm.role_id == role_id)
        .order_by(RoleApplicationForm.version.desc())
    )
    return form_response(form) if form else None


async def upsert_application_form(
    db: AsyncSession,
    institution_id: UUID | None,
    role_id: UUID,
    actor_user_id: UUID,
    payload: ApplicationFormUpdate,
) -> RoleApplicationForm:
    institution = _institution(institution_id)
    role = await _owned_role(db, institution, role_id)
    if role.status in {PublicationStatus.CLOSED.value, PublicationStatus.ARCHIVED.value}:
        raise ApplicationPacketError("role_application_form_locked")
    form = await db.scalar(
        select(RoleApplicationForm).where(
            RoleApplicationForm.role_id == role.id,
            RoleApplicationForm.status == "draft",
        )
    )
    if form is None:
        version = (
            await db.scalar(
                select(func.max(RoleApplicationForm.version)).where(
                    RoleApplicationForm.role_id == role.id
                )
            )
            or 0
        ) + 1
        form = RoleApplicationForm(
            institution_id=institution,
            role_id=role.id,
            version=version,
            created_by_user_id=actor_user_id,
            status="draft",
            **payload.model_dump(mode="json"),
        )
        db.add(form)
    else:
        for key, value in payload.model_dump(mode="json").items():
            setattr(form, key, value)
    await db.flush()
    await db.refresh(form)
    return form


async def publish_application_form(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID
) -> RoleApplicationForm:
    await _owned_role(db, institution_id, role_id)
    form = await db.scalar(
        select(RoleApplicationForm)
        .where(
            RoleApplicationForm.role_id == role_id,
            RoleApplicationForm.status == "draft",
        )
        .with_for_update()
    )
    if form is None:
        raise ApplicationPacketError("application_form_draft_not_found")
    form.status = "published"
    form.published_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(form)
    return form


async def publish_pending_form_for_role(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID
) -> RoleApplicationForm | None:
    form = await db.scalar(
        select(RoleApplicationForm).where(
            RoleApplicationForm.role_id == role_id,
            RoleApplicationForm.institution_id == _institution(institution_id),
            RoleApplicationForm.status == "draft",
        )
    )
    if form is None:
        return None
    form.status = "published"
    form.published_at = datetime.now(UTC)
    await db.flush()
    return form


async def _owned_draft(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    draft_id: UUID,
    *,
    lock: bool = False,
) -> ApplicationDraft:
    query = select(ApplicationDraft).where(
        ApplicationDraft.id == draft_id,
        ApplicationDraft.institution_id == _institution(institution_id),
        ApplicationDraft.student_user_id == student_user_id,
    )
    draft = await db.scalar(query.with_for_update() if lock else query)
    if draft is None:
        raise ApplicationPacketError("application_draft_not_found")
    if draft.submitted_application_id is None and _utc(draft.expires_at) <= datetime.now(UTC):
        raise ApplicationPacketError("application_draft_expired")
    return draft


def _check_revision(draft: ApplicationDraft, expected_revision: int) -> None:
    if draft.revision != expected_revision:
        raise ApplicationPacketError("application_draft_revision_conflict")


async def create_or_resume_draft(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    role_id: UUID,
) -> ApplicationDraft:
    institution = _institution(institution_id)
    now = datetime.now(UTC)
    await db.execute(
        delete(ApplicationDraft).where(
            ApplicationDraft.institution_id == institution,
            ApplicationDraft.student_user_id == student_user_id,
            ApplicationDraft.expires_at <= now,
            ApplicationDraft.submitted_application_id.is_(None),
        )
    )
    row = (
        await db.execute(
            select(PlacementRole, PlacementDrive)
            .join(PlacementDrive, PlacementDrive.id == PlacementRole.drive_id)
            .where(
                PlacementRole.id == role_id,
                PlacementRole.institution_id == institution,
                PlacementRole.status == PublicationStatus.PUBLISHED.value,
                PlacementDrive.status == PublicationStatus.PUBLISHED.value,
                PlacementDrive.opens_at <= now,
                PlacementDrive.deadline_at >= now,
            )
        )
    ).one_or_none()
    if row is None:
        raise ApplicationPacketError("opportunity_not_available")
    role, drive = row
    existing = await db.scalar(
        select(ApplicationDraft).where(
            ApplicationDraft.institution_id == institution,
            ApplicationDraft.student_user_id == student_user_id,
            ApplicationDraft.role_id == role.id,
        )
    )
    if existing is not None:
        return existing
    form = await db.scalar(
        select(RoleApplicationForm)
        .where(
            RoleApplicationForm.role_id == role.id,
            RoleApplicationForm.status == "published",
        )
        .order_by(RoleApplicationForm.version.desc())
    )
    draft = ApplicationDraft(
        institution_id=institution,
        student_user_id=student_user_id,
        role_id=role.id,
        form_version_id=form.id if form else None,
        current_step="resume",
        revision=1,
        expires_at=drive.deadline_at + timedelta(days=30),
        last_saved_at=now,
    )
    db.add(draft)
    await db.flush()
    await db.refresh(draft)
    return draft


async def _draft_context(
    db: AsyncSession, draft: ApplicationDraft
) -> tuple[PlacementRole, PlacementDrive, Company]:
    row = (
        await db.execute(
            select(PlacementRole, PlacementDrive, Company)
            .join(PlacementDrive, PlacementDrive.id == PlacementRole.drive_id)
            .join(Company, Company.id == PlacementDrive.company_id)
            .where(PlacementRole.id == draft.role_id)
        )
    ).one()
    return row[0], row[1], row[2]


async def draft_response(db: AsyncSession, draft: ApplicationDraft) -> ApplicationDraftResponse:
    role, drive, company = await _draft_context(db, draft)
    form = (
        await db.get(RoleApplicationForm, draft.form_version_id) if draft.form_version_id else None
    )
    resume = (
        await db.get(ResumeVersion, draft.resume_version_id) if draft.resume_version_id else None
    )
    disclosure = await db.scalar(
        select(ApplicationDisclosureDraft).where(
            ApplicationDisclosureDraft.application_draft_id == draft.id
        )
    )
    answers: dict[str, DisclosureAnswer] = {}
    if disclosure is not None:
        decoded = decrypt_sensitive_payload(
            disclosure.encrypted_payload, f"application-disclosure-draft:{draft.id}"
        )
        raw_answers = decoded.get("answers", {})
        if isinstance(raw_answers, dict):
            answers = _DISCLOSURE_ANSWERS.validate_python(raw_answers)
    return ApplicationDraftResponse(
        id=draft.id,
        role_id=draft.role_id,
        role_title=role.title,
        company_name=company.name,
        deadline_at=drive.deadline_at,
        current_step=draft.current_step,
        revision=draft.revision,
        expires_at=draft.expires_at,
        last_saved_at=draft.last_saved_at,
        profile_revision=draft.profile_revision,
        resume=(
            DraftResumeSummary(
                id=resume.id,
                original_name=resume.original_name,
                version_number=resume.version_number,
                created_at=resume.created_at,
                parent_version_id=resume.parent_version_id,
            )
            if resume
            else None
        ),
        form=form_response(form) if form else None,
        disclosure_answers=answers,
        disclosure_completed=disclosure is not None or form is None,
        submitted_application_id=draft.submitted_application_id,
    )


async def get_draft(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID, draft_id: UUID
) -> ApplicationDraftResponse:
    return await draft_response(
        db, await _owned_draft(db, institution_id, student_user_id, draft_id)
    )


async def select_draft_resume(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    draft_id: UUID,
    resume_version_id: UUID,
    expected_revision: int,
) -> ApplicationDraft:
    institution = _institution(institution_id)
    draft = await _owned_draft(db, institution, student_user_id, draft_id, lock=True)
    _check_revision(draft, expected_revision)
    resume = await db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == resume_version_id,
            ResumeVersion.user_id == student_user_id,
            ResumeVersion.institution_id == institution,
            ResumeVersion.status == ResumeStatus.COMPLETED.value,
            ResumeVersion.scan_status == ScanStatus.CLEAN.value,
            ResumeVersion.content_type == "application/pdf",
        )
    )
    if resume is None:
        raise ApplicationPacketError("resume_version_not_selectable")
    draft.resume_version_id = resume.id
    draft.current_step = "profile"
    draft.revision += 1
    draft.last_saved_at = datetime.now(UTC)
    await db.flush()
    return draft


def _profile_complete(profile: StudentProfile) -> bool:
    return all(
        [
            profile.full_name,
            profile.phone,
            profile.education,
            profile.department,
            profile.academic_year,
            profile.city,
            profile.country_code,
        ]
    )


async def confirm_draft_profile(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    draft_id: UUID,
    profile_revision: int,
    expected_revision: int,
) -> ApplicationDraft:
    draft = await _owned_draft(db, institution_id, student_user_id, draft_id, lock=True)
    _check_revision(draft, expected_revision)
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == student_user_id,
            StudentProfile.institution_id == _institution(institution_id),
        )
    )
    if profile is None or profile.revision != profile_revision:
        raise ApplicationPacketError("profile_revision_conflict")
    if not _profile_complete(profile):
        raise ApplicationPacketError("application_profile_incomplete")
    draft.profile_revision = profile.revision
    draft.current_step = "disclosures"
    draft.revision += 1
    draft.last_saved_at = datetime.now(UTC)
    await db.flush()
    return draft


def _validate_answers(
    form: RoleApplicationForm | None, answers: dict[str, DisclosureAnswer]
) -> dict[str, DisclosureAnswer]:
    if form is None:
        if answers:
            raise ApplicationPacketError("application_form_not_configured")
        return {}
    questions = {item.id: item for item in form_response(form).questions}
    if not set(answers).issubset(questions):
        raise ApplicationPacketError("disclosure_answer_unknown_question")
    normalized: dict[str, DisclosureAnswer] = {}
    for question_id, value in answers.items():
        question = questions[question_id]
        if value == "prefer_not_to_answer":
            normalized[question_id] = value
            continue
        if question.type == "boolean":
            if not isinstance(value, bool):
                raise ApplicationPacketError("disclosure_answer_invalid")
        elif question.type == "single_select":
            if not isinstance(value, str) or value not in question.options:
                raise ApplicationPacketError("disclosure_answer_invalid")
        else:
            if (
                not isinstance(value, list)
                or not value
                or len(value) != len(set(value))
                or not set(value).issubset(question.options)
            ):
                raise ApplicationPacketError("disclosure_answer_invalid")
        normalized[question_id] = value
    return normalized


async def save_draft_disclosures(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    draft_id: UUID,
    answers: dict[str, DisclosureAnswer],
    expected_revision: int,
) -> ApplicationDraft:
    draft = await _owned_draft(db, institution_id, student_user_id, draft_id, lock=True)
    _check_revision(draft, expected_revision)
    form = (
        await db.get(RoleApplicationForm, draft.form_version_id) if draft.form_version_id else None
    )
    normalized = _validate_answers(form, answers)
    encrypted = encrypt_sensitive_payload(
        {"answers": normalized}, f"application-disclosure-draft:{draft.id}"
    )
    record = await db.scalar(
        select(ApplicationDisclosureDraft).where(
            ApplicationDisclosureDraft.application_draft_id == draft.id
        )
    )
    now = datetime.now(UTC)
    if record is None:
        db.add(
            ApplicationDisclosureDraft(
                application_draft_id=draft.id,
                encrypted_payload=encrypted,
                answered_at=now,
            )
        )
    else:
        record.encrypted_payload = encrypted
        record.answered_at = now
    draft.current_step = "review"
    draft.revision += 1
    draft.last_saved_at = now
    await db.flush()
    return draft


async def _profile_snapshot(
    db: AsyncSession, draft: ApplicationDraft
) -> tuple[StudentProfile, dict[str, object]]:
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == draft.student_user_id,
            StudentProfile.institution_id == draft.institution_id,
        )
    )
    user = await db.get(User, draft.student_user_id)
    if (
        profile is None
        or user is None
        or draft.profile_revision is None
        or profile.revision != draft.profile_revision
        or not _profile_complete(profile)
    ):
        raise ApplicationPacketError("profile_revision_conflict")
    return profile, {
        "profile_revision": profile.revision,
        "full_name": profile.full_name,
        "email": user.email,
        "phone": profile.phone,
        "education": list(profile.education),
        "department": profile.department,
        "academic_year": profile.academic_year,
        "city": profile.city,
        "country_code": profile.country_code,
        "captured_at": datetime.now(UTC).isoformat(),
    }


async def review_draft(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID, draft_id: UUID
) -> ApplicationReviewResponse:
    draft = await _owned_draft(db, institution_id, student_user_id, draft_id)
    if draft.resume_version_id is None:
        raise ApplicationPacketError("application_resume_required")
    _, snapshot = await _profile_snapshot(db, draft)
    response = await draft_response(db, draft)
    if not response.disclosure_completed:
        raise ApplicationPacketError("application_disclosures_incomplete")
    return ApplicationReviewResponse(
        draft=response,
        profile_snapshot=snapshot,
        immutable_notice=(
            "After submission, this application becomes an immutable snapshot. "
            "Your profile can still be updated for future roles."
        ),
    )


async def submit_draft(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    draft_id: UUID,
    expected_revision: int,
    idempotency_key: str,
) -> tuple[Application, bool]:
    institution = _institution(institution_id)
    draft = await _owned_draft(db, institution, student_user_id, draft_id, lock=True)
    if draft.submitted_application_id is not None:
        application = await db.get(Application, draft.submitted_application_id)
        if application is None:
            raise ApplicationPacketError("application_not_found")
        return application, True
    _check_revision(draft, expected_revision)
    if draft.resume_version_id is None:
        raise ApplicationPacketError("application_resume_required")
    _, profile_snapshot = await _profile_snapshot(db, draft)
    form = (
        await db.get(RoleApplicationForm, draft.form_version_id) if draft.form_version_id else None
    )
    disclosure_draft = await db.scalar(
        select(ApplicationDisclosureDraft).where(
            ApplicationDisclosureDraft.application_draft_id == draft.id
        )
    )
    if form is not None and disclosure_draft is None:
        raise ApplicationPacketError("application_disclosures_incomplete")
    application, replayed = await create_application(
        db,
        institution,
        student_user_id,
        idempotency_key,
        ApplicationCreate(role_id=draft.role_id, resume_version_id=draft.resume_version_id),
    )
    if replayed:
        draft.submitted_application_id = application.id
        return application, True
    application.profile_snapshot = profile_snapshot
    application.application_form_snapshot = (
        form_response(form).model_dump(mode="json") if form else {}
    )
    application.disclosure_status = "not_configured"
    if form is not None and disclosure_draft is not None:
        decoded = decrypt_sensitive_payload(
            disclosure_draft.encrypted_payload,
            f"application-disclosure-draft:{draft.id}",
        )
        answers = decoded.get("answers", {})
        application.disclosure_status = "collected" if answers else "declined"
        db.add(
            ApplicationDisclosure(
                institution_id=institution,
                application_id=application.id,
                form_version_id=form.id,
                encrypted_payload=encrypt_sensitive_payload(
                    {"answers": answers}, f"application-disclosure:{application.id}"
                ),
                retention_until=datetime.now(UTC) + timedelta(days=form.retention_days),
                created_at=datetime.now(UTC),
            )
        )
        await db.delete(disclosure_draft)
    draft.submitted_application_id = application.id
    draft.current_step = "submitted"
    draft.revision += 1
    draft.last_saved_at = datetime.now(UTC)
    await db.flush()
    return application, False


async def purge_expired_application_packet_data(
    db: AsyncSession, *, now: datetime | None = None
) -> tuple[int, int]:
    """Delete expired abandoned drafts and disclosures after their published retention window."""
    current = now or datetime.now(UTC)
    disclosure_result = await db.execute(
        delete(ApplicationDisclosure).where(ApplicationDisclosure.retention_until <= current)
    )
    draft_result = await db.execute(
        delete(ApplicationDraft).where(
            ApplicationDraft.expires_at <= current,
            ApplicationDraft.submitted_application_id.is_(None),
        )
    )
    await db.flush()
    return (
        int(getattr(disclosure_result, "rowcount", 0) or 0),
        int(getattr(draft_result, "rowcount", 0) or 0),
    )


async def delete_draft(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID, draft_id: UUID
) -> None:
    draft = await _owned_draft(db, institution_id, student_user_id, draft_id, lock=True)
    if draft.submitted_application_id is not None:
        raise ApplicationPacketError("submitted_application_draft_immutable")
    await db.delete(draft)
    await db.flush()


async def read_student_disclosure(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    application_id: UUID,
) -> ApplicationDisclosureResponse:
    row = (
        await db.execute(
            select(ApplicationDisclosure, RoleApplicationForm)
            .join(
                RoleApplicationForm, RoleApplicationForm.id == ApplicationDisclosure.form_version_id
            )
            .join(Application, Application.id == ApplicationDisclosure.application_id)
            .where(
                ApplicationDisclosure.application_id == application_id,
                ApplicationDisclosure.institution_id == _institution(institution_id),
                Application.student_user_id == student_user_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise ApplicationPacketError("application_disclosure_not_found")
    disclosure, form = row
    decoded = decrypt_sensitive_payload(
        disclosure.encrypted_payload, f"application-disclosure:{application_id}"
    )
    answers = decoded.get("answers", {})
    return ApplicationDisclosureResponse(
        application_id=application_id,
        form=form_response(form),
        answers=_DISCLOSURE_ANSWERS.validate_python(answers),
        retention_until=disclosure.retention_until,
    )


async def read_compliance_disclosure(
    db: AsyncSession, institution_id: UUID | None, application_id: UUID
) -> ApplicationDisclosureResponse:
    row = (
        await db.execute(
            select(ApplicationDisclosure, RoleApplicationForm)
            .join(
                RoleApplicationForm, RoleApplicationForm.id == ApplicationDisclosure.form_version_id
            )
            .where(
                ApplicationDisclosure.application_id == application_id,
                ApplicationDisclosure.institution_id == _institution(institution_id),
            )
        )
    ).one_or_none()
    if row is None:
        raise ApplicationPacketError("application_disclosure_not_found")
    disclosure, form = row
    decoded = decrypt_sensitive_payload(
        disclosure.encrypted_payload, f"application-disclosure:{application_id}"
    )
    answers = decoded.get("answers", {})
    return ApplicationDisclosureResponse(
        application_id=application_id,
        form=form_response(form),
        answers=_DISCLOSURE_ANSWERS.validate_python(answers),
        retention_until=disclosure.retention_until,
    )
