from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import Institution, User
from app.models.profile import StudentProfile
from app.modules.auth.institutional_identity import (
    InstitutionalEmailError,
    validate_pcco_email_prn_consistency,
)
from app.modules.communications.service import record_product_event
from app.modules.profiles.schemas import (
    EducationUpdate,
    IdentityUpdate,
    LinksUpdate,
    PreferencesUpdate,
    ProfileResponse,
    ProfileUpdate,
    ReadinessItem,
    SkillsUpdate,
)

ProfilePayload = (
    ProfileUpdate
    | IdentityUpdate
    | EducationUpdate
    | SkillsUpdate
    | PreferencesUpdate
    | LinksUpdate
)


class ProfileConflictError(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("profile_revision_conflict")
        self.current_revision = current_revision


class ProfileIdentityConflictError(ValueError):
    pass


def readiness(profile: StudentProfile) -> tuple[int, bool, list[ReadinessItem]]:
    items = [
        ReadinessItem(
            key="identity",
            label="Basic identity",
            complete=all(
                [profile.full_name, profile.institution_name, profile.prn, profile.department]
            ),
            required=True,
        ),
        ReadinessItem(
            key="education", label="Education", complete=bool(profile.education), required=True
        ),
        ReadinessItem(
            key="role", label="Target role", complete=bool(profile.target_roles), required=True
        ),
        ReadinessItem(key="skills", label="Skills", complete=bool(profile.skills), required=False),
        ReadinessItem(
            key="links",
            label="GitHub or portfolio",
            complete=bool(profile.external_links),
            required=False,
        ),
        ReadinessItem(key="resume", label="Resume", complete=False, required=False),
    ]
    score = round(sum(item.complete for item in items) / len(items) * 100)
    complete = all(item.complete for item in items if item.required)
    return score, complete, items


async def get_or_create(
    db: AsyncSession,
    user: User,
    institution_id: UUID | None = None,
    *,
    lock: bool = False,
) -> StudentProfile:
    query = select(StudentProfile).where(StudentProfile.user_id == user.id)
    if lock:
        query = query.with_for_update()
    profile = await db.scalar(query)
    changed = False
    if profile is None:
        profile = StudentProfile(user_id=user.id, institution_id=institution_id)
        db.add(profile)
        changed = True
    elif profile.institution_id is None and institution_id is not None:
        profile.institution_id = institution_id
        changed = True
    if profile.institution_id is not None:
        institution_name = await db.scalar(
            select(Institution.name).where(Institution.id == profile.institution_id)
        )
        if institution_name is not None and profile.institution_name != institution_name:
            profile.institution_name = institution_name
            changed = True
    if changed:
        await db.commit()
        await db.refresh(profile)
    return profile


async def update_profile(
    db: AsyncSession,
    user: User,
    payload: ProfilePayload,
    institution_id: UUID | None = None,
) -> StudentProfile:
    profile = await get_or_create(db, user, institution_id, lock=True)
    was_complete = profile.is_complete
    data = payload.model_dump(exclude_unset=True)
    expected_revision = data.pop("expected_revision", None)
    if expected_revision is not None and expected_revision != profile.revision:
        raise ProfileConflictError(profile.revision)
    if "prn" in data and data["prn"]:
        try:
            validate_pcco_email_prn_consistency(user.email, str(data["prn"]))
        except InstitutionalEmailError as error:
            raise ProfileIdentityConflictError(str(error)) from error
    if "prn" in data and profile.prn != data["prn"]:
        profile.prn_verified_at = None
        profile.prn_verified_by_user_id = None
    links = dict(profile.external_links)
    for key in ("github_url", "portfolio_url"):
        if key in data:
            value = data.pop(key)
            if value:
                links[key.removesuffix("_url")] = value
            else:
                links.pop(key.removesuffix("_url"), None)
    for key, value in data.items():
        if key in {"education", "skills"} and value is not None:
            value = [item if isinstance(item, dict) else item.model_dump() for item in value]
        setattr(profile, key, value)
    profile.external_links = links
    profile.readiness, profile.is_complete, _ = readiness(profile)
    profile.revision += 1
    await record_product_event(
        db,
        event_name="onboarding_step_completed",
        route_group="profile",
        institution_id=institution_id,
        dedupe_key=f"onboarding-step:{user.id}:{profile.onboarding_step}",
    )
    if profile.is_complete and not was_complete:
        await record_product_event(
            db,
            event_name="profile_completed",
            route_group="profile",
            institution_id=institution_id,
            dedupe_key=f"profile-completed:{user.id}",
        )
    await db.commit()
    await db.refresh(profile)
    return profile


def to_response(profile: StudentProfile, account_email: str | None = None) -> ProfileResponse:
    score, complete, checklist = readiness(profile)
    return ProfileResponse(
        id=profile.id,
        institution_id=profile.institution_id,
        full_name=profile.full_name,
        date_of_birth=profile.date_of_birth,
        institution_name=profile.institution_name,
        prn=profile.prn,
        department=profile.department,
        academic_year=profile.academic_year,
        phone=profile.phone,
        account_email=account_email,
        city=profile.city,
        country_code=profile.country_code,
        education=profile.education,
        skills=profile.skills,
        target_roles=profile.target_roles,
        external_links=profile.external_links,
        onboarding_step=profile.onboarding_step,
        revision=profile.revision,
        updated_at=profile.updated_at,
        readiness=score,
        is_complete=complete,
        checklist=checklist,
    )
