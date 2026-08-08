from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.profile import StudentProfile
from app.modules.profiles.schemas import ProfileResponse, ProfileUpdate, ReadinessItem


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


async def get_or_create(db: AsyncSession, user: User) -> StudentProfile:
    profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
    if profile is None:
        profile = StudentProfile(user_id=user.id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


async def update_profile(db: AsyncSession, user: User, payload: ProfileUpdate) -> StudentProfile:
    profile = await get_or_create(db, user)
    data = payload.model_dump(exclude_unset=True)
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
    await db.commit()
    await db.refresh(profile)
    return profile


def to_response(profile: StudentProfile) -> ProfileResponse:
    score, complete, checklist = readiness(profile)
    return ProfileResponse(
        full_name=profile.full_name,
        institution_name=profile.institution_name,
        prn=profile.prn,
        department=profile.department,
        academic_year=profile.academic_year,
        phone=profile.phone,
        education=profile.education,
        skills=profile.skills,
        target_roles=profile.target_roles,
        external_links=profile.external_links,
        onboarding_step=profile.onboarding_step,
        readiness=score,
        is_complete=complete,
        checklist=checklist,
    )
