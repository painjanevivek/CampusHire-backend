from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.auth import (
    Institution,
    InstitutionDomain,
    MembershipInvitation,
    RosterImport,
    User,
    UserRole,
)
from app.models.onboarding import (
    InstitutionCampus,
    InstitutionOnboarding,
    InstitutionProgram,
    StudentCareerPreference,
    StudentCertification,
    StudentEducation,
    StudentExperience,
    StudentPlacementParticipation,
    StudentProject,
)
from app.models.profile import StudentProfile
from app.modules.audit.service import record_audit_event
from app.modules.auth.institutional_identity import (
    InstitutionalEmailError,
    validate_pcco_email_prn_consistency,
)
from app.modules.auth.security import hash_secret, new_secret, normalize_email
from app.modules.communications.service import enqueue_email, record_product_event
from app.modules.onboarding.schemas import (
    InstitutionOnboardingResponse,
    InstitutionOnboardingUpdate,
    StudentOnboardingResponse,
    StudentOnboardingUpdate,
)
from app.modules.profiles.service import get_or_create


class OnboardingConflictError(Exception):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision


class OnboardingValidationError(Exception):
    pass


def _row(item: object, *fields: str) -> dict[str, object]:
    return {field: getattr(item, field) for field in fields}


async def student_onboarding_response(
    db: AsyncSession, profile: StudentProfile
) -> StudentOnboardingResponse:
    education = list(
        (
            await db.scalars(
                select(StudentEducation)
                .where(StudentEducation.profile_id == profile.id)
                .order_by(StudentEducation.created_at, StudentEducation.id)
            )
        ).all()
    )
    experience = list(
        (
            await db.scalars(
                select(StudentExperience)
                .where(StudentExperience.profile_id == profile.id)
                .order_by(StudentExperience.start_date.desc(), StudentExperience.id)
            )
        ).all()
    )
    projects = list(
        (
            await db.scalars(
                select(StudentProject)
                .where(StudentProject.profile_id == profile.id)
                .order_by(StudentProject.created_at, StudentProject.id)
            )
        ).all()
    )
    certifications = list(
        (
            await db.scalars(
                select(StudentCertification)
                .where(StudentCertification.profile_id == profile.id)
                .order_by(StudentCertification.created_at, StudentCertification.id)
            )
        ).all()
    )
    career = await db.get(StudentCareerPreference, profile.id)
    participation = await db.get(StudentPlacementParticipation, profile.id)
    return StudentOnboardingResponse(
        profile_id=profile.id,
        institution_id=profile.institution_id,
        institution_name=profile.institution_name,
        revision=profile.revision,
        current_step=profile.onboarding_step,
        completed=profile.onboarding_completed_at is not None,
        completed_at=profile.onboarding_completed_at,
        identity={
            "full_name": profile.full_name,
            "prn": profile.prn,
            "department": profile.department,
            "graduation_year": profile.graduation_year,
        },
        education=[
            _row(
                item,
                "id",
                "qualification_level",
                "degree",
                "branch",
                "institution",
                "start_year",
                "graduation_year",
                "score",
                "score_scale",
                "active_backlogs",
            )
            for item in education
        ],
        experience=[
            _row(
                item,
                "id",
                "organization",
                "title",
                "start_date",
                "end_date",
                "is_current",
                "responsibilities",
            )
            for item in experience
        ],
        projects=[
            _row(
                item,
                "id",
                "title",
                "project_type",
                "description",
                "technologies",
                "outcomes",
                "project_url",
            )
            for item in projects
        ],
        skills=profile.skills,
        certifications=[
            _row(item, "id", "name", "issuer", "issued_on", "expires_on", "credential_url")
            for item in certifications
        ],
        career_preferences=(
            _row(career, "target_roles", "industries", "locations", "job_types", "work_modes")
            if career
            else None
        ),
        placement_participation=(
            _row(
                participation,
                "placement_cycle",
                "communication_channels",
                "visibility",
                "privacy_accepted",
                "privacy_accepted_at",
            )
            if participation
            else None
        ),
    )


async def get_student_onboarding(
    db: AsyncSession, user: User, institution_id: UUID | None
) -> StudentOnboardingResponse:
    profile = await get_or_create(db, user, institution_id)
    return await student_onboarding_response(db, profile)


async def update_student_onboarding(
    db: AsyncSession,
    *,
    user: User,
    institution_id: UUID | None,
    payload: StudentOnboardingUpdate,
    correlation_id: str | None,
) -> StudentOnboardingResponse:
    profile = await get_or_create(db, user, institution_id, lock=True)
    if payload.expected_revision != profile.revision:
        raise OnboardingConflictError(profile.revision)
    if payload.step == 1 and payload.identity:
        try:
            validate_pcco_email_prn_consistency(user.email, payload.identity.prn)
        except InstitutionalEmailError as error:
            raise OnboardingValidationError(str(error)) from error
        institution = await db.get(Institution, institution_id) if institution_id else None
        if profile.prn != payload.identity.prn:
            profile.prn_verified_at = None
            profile.prn_verified_by_user_id = None
        profile.full_name = payload.identity.full_name
        profile.institution_name = institution.name if institution else profile.institution_name
        profile.prn = payload.identity.prn
        profile.department = payload.identity.department
        profile.graduation_year = payload.identity.graduation_year
        profile.academic_year = str(payload.identity.graduation_year)
    elif payload.step == 2 and payload.education is not None:
        await db.execute(delete(StudentEducation).where(StudentEducation.profile_id == profile.id))
        db.add_all(
            [
                StudentEducation(profile_id=profile.id, **item.model_dump())
                for item in payload.education
            ]
        )
        profile.education = [
            {
                "degree": item.degree,
                "branch": item.branch,
                "institution": item.institution,
                "start_year": item.start_year or item.graduation_year,
                "graduation_year": item.graduation_year,
                "score": item.score,
                "score_scale": item.score_scale,
            }
            for item in payload.education[:6]
        ]
    elif payload.step == 3 and payload.experience is not None:
        await db.execute(
            delete(StudentExperience).where(StudentExperience.profile_id == profile.id)
        )
        db.add_all(
            [
                StudentExperience(profile_id=profile.id, **item.model_dump())
                for item in payload.experience
            ]
        )
    elif payload.step == 4 and payload.projects_skills:
        await db.execute(delete(StudentProject).where(StudentProject.profile_id == profile.id))
        await db.execute(
            delete(StudentCertification).where(StudentCertification.profile_id == profile.id)
        )
        project_data = payload.projects_skills.projects
        certification_data = payload.projects_skills.certifications
        db.add_all(
            [
                StudentProject(profile_id=profile.id, **item.model_dump(mode="json"))
                for item in project_data
            ]
        )
        db.add_all(
            [
                StudentCertification(profile_id=profile.id, **item.model_dump(mode="json"))
                for item in certification_data
            ]
        )
        profile.skills = [
            {"name": skill.strip(), "proficiency": "comfortable"}
            for skill in payload.projects_skills.skills
            if skill.strip()
        ]
    elif payload.step == 5 and payload.career_preferences:
        career = await db.get(StudentCareerPreference, profile.id)
        values = payload.career_preferences.model_dump()
        if career is None:
            career = StudentCareerPreference(profile_id=profile.id, **values)
            db.add(career)
        else:
            for key, value in values.items():
                setattr(career, key, value)
        profile.target_roles = payload.career_preferences.target_roles[:5]
    elif payload.step == 6 and payload.placement_participation:
        participation = await db.get(StudentPlacementParticipation, profile.id)
        values = payload.placement_participation.model_dump()
        if participation is None:
            participation = StudentPlacementParticipation(profile_id=profile.id, **values)
            db.add(participation)
        else:
            for key, value in values.items():
                setattr(participation, key, value)
        participation.privacy_accepted_at = datetime.now(UTC)
        record_audit_event(
            db,
            actor_user_id=user.id,
            institution_id=institution_id,
            event_type="onboarding.student.participation_updated",
            resource_type="student_profile",
            resource_id=str(profile.id),
            correlation_id=correlation_id,
            details={"visibility": participation.visibility},
        )
    elif payload.step == 7 and payload.review:
        career = await db.get(StudentCareerPreference, profile.id)
        participation = await db.get(StudentPlacementParticipation, profile.id)
        education_exists = await db.scalar(
            select(StudentEducation.id).where(StudentEducation.profile_id == profile.id).limit(1)
        )
        required = (
            profile.full_name,
            profile.prn,
            profile.department,
            profile.graduation_year,
            education_exists,
            career and career.target_roles,
            participation and participation.privacy_accepted,
        )
        if not all(required):
            raise OnboardingValidationError("Complete all required onboarding fields before review")
        profile.onboarding_completed_at = datetime.now(UTC)
    profile.onboarding_step = min(payload.step + 1, 7)
    profile.revision += 1
    await record_product_event(
        db,
        event_name="onboarding_step_completed",
        route_group="student_onboarding",
        institution_id=institution_id,
        dedupe_key=f"student-onboarding:{profile.id}:{payload.step}:{profile.revision}",
    )
    await db.commit()
    await db.refresh(profile)
    return await student_onboarding_response(db, profile)


async def get_institution_onboarding(
    db: AsyncSession, institution_id: UUID
) -> InstitutionOnboardingResponse:
    institution = await db.get(Institution, institution_id)
    if institution is None:
        raise OnboardingValidationError("Institution not found")
    state = await db.get(InstitutionOnboarding, institution_id)
    if state is None:
        state = InstitutionOnboarding(institution_id=institution_id)
        db.add(state)
        await db.commit()
        await db.refresh(state)
    return InstitutionOnboardingResponse(
        institution_id=institution.id,
        institution_name=institution.name,
        institution_active=institution.is_active,
        revision=state.revision,
        current_step=state.current_step,
        completed_steps=state.completed_steps,
        step_data=state.step_data,
        activated_at=state.activated_at,
    )


async def update_institution_onboarding(
    db: AsyncSession,
    *,
    institution_id: UUID,
    actor_user_id: UUID,
    payload: InstitutionOnboardingUpdate,
    correlation_id: str | None,
) -> InstitutionOnboardingResponse:
    institution = await db.scalar(
        select(Institution).where(Institution.id == institution_id).with_for_update()
    )
    if institution is None:
        raise OnboardingValidationError("Institution not found")
    state = await db.get(InstitutionOnboarding, institution_id)
    if state is None:
        state = InstitutionOnboarding(institution_id=institution_id)
        db.add(state)
        await db.flush()
    if payload.expected_revision != state.revision:
        raise OnboardingConflictError(state.revision)
    data: dict[str, Any] = dict(state.step_data)
    value = payload.model_dump(
        mode="json", exclude={"expected_revision", "step"}, exclude_none=True
    )
    data[str(payload.step)] = value
    if payload.step == 2 and payload.institution:
        domain = await db.scalar(
            select(InstitutionDomain).where(
                InstitutionDomain.institution_id == institution_id,
                InstitutionDomain.verification_status == "verified",
            )
        )
        if (
            domain is None
            or payload.institution.domain.casefold() != domain.domain
            or payload.institution.official_name.casefold() != institution.name.casefold()
        ):
            raise OnboardingValidationError("Institution identity does not match verified records")
    if payload.step == 3 and payload.campuses is not None:
        campus_ids = select(InstitutionCampus.id).where(
            InstitutionCampus.institution_id == institution_id
        )
        await db.execute(
            delete(InstitutionProgram).where(InstitutionProgram.campus_id.in_(campus_ids))
        )
        await db.execute(
            delete(InstitutionCampus).where(InstitutionCampus.institution_id == institution_id)
        )
        for campus_data in payload.campuses:
            campus = InstitutionCampus(institution_id=institution_id, name=campus_data.name)
            db.add(campus)
            await db.flush()
            db.add_all(
                [
                    InstitutionProgram(campus_id=campus.id, **program.model_dump())
                    for program in campus_data.programs
                ]
            )
    if payload.step == 5 and payload.roster and payload.roster.roster_import_id:
        roster = await db.scalar(
            select(RosterImport.id).where(
                RosterImport.id == payload.roster.roster_import_id,
                RosterImport.institution_id == institution_id,
            )
        )
        if roster is None:
            raise OnboardingValidationError("Roster import is outside this institution")
    completed = sorted(set(state.completed_steps) | {payload.step})
    if payload.step == 7:
        domain_verified = await db.scalar(
            select(InstitutionDomain.id).where(
                InstitutionDomain.institution_id == institution_id,
                InstitutionDomain.verification_status == "verified",
            )
        )
        if not set(range(1, 7)).issubset(completed) or domain_verified is None:
            raise OnboardingValidationError(
                "Complete all verified onboarding steps before activation"
            )
        institution.is_active = True
        state.activated_at = datetime.now(UTC)
        if payload.review:
            frontend = str(get_settings().frontend_origins[0]).rstrip("/")
            for address in payload.review.invite_team_emails:
                email = normalize_email(str(address))
                existing_user = await db.scalar(select(User.id).where(User.email == email))
                existing_invitation = await db.scalar(
                    select(MembershipInvitation.id).where(
                        MembershipInvitation.institution_id == institution_id,
                        MembershipInvitation.email == email,
                        MembershipInvitation.accepted_at.is_(None),
                        MembershipInvitation.revoked_at.is_(None),
                    )
                )
                if existing_user is not None or existing_invitation is not None:
                    continue
                raw_token = new_secret()
                invitation = MembershipInvitation(
                    institution_id=institution_id,
                    email=email,
                    role=UserRole.TNP_ADMIN.value,
                    token_hash=hash_secret(raw_token),
                    expires_at=datetime.now(UTC)
                    + timedelta(hours=get_settings().invitation_ttl_hours),
                    created_by_user_id=actor_user_id,
                )
                db.add(invitation)
                await db.flush()
                await enqueue_email(
                    db,
                    institution_id=institution_id,
                    recipient_email=email,
                    category="account",
                    template_key="invitation",
                    variables={
                        "institution_name": institution.name,
                        "activation_url": f"{frontend}/activate/{raw_token}",
                    },
                    dedupe_key=f"invitation:{invitation.id}",
                )
                record_audit_event(
                    db,
                    actor_user_id=actor_user_id,
                    institution_id=institution_id,
                    event_type="onboarding.institution.team_invited",
                    resource_type="membership_invitation",
                    resource_id=str(invitation.id),
                    correlation_id=correlation_id,
                )
    state.step_data = data
    state.completed_steps = completed
    state.current_step = min(payload.step + 1, 7)
    state.revision += 1
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="onboarding.institution.step_updated",
        resource_type="institution_onboarding",
        resource_id=str(institution_id),
        correlation_id=correlation_id,
        details={"step": payload.step, "activated": institution.is_active},
    )
    await db.commit()
    return await get_institution_onboarding(db, institution_id)
