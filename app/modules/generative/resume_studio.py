from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.generative_ai import ProposalStatus
from app.models.onboarding import StudentEducation
from app.models.profile import StudentProfile
from app.models.resume import ResumeVersion
from app.modules.generative.schemas import ResumeDraft
from app.modules.generative.service import ProposalValidationError, get_owned_proposal
from app.modules.resumes.builder import ResumeContent
from app.modules.resumes.storage import build_object_store
from app.modules.resumes.workflow import create_generated_version


async def materialize_resume_version(
    db: AsyncSession,
    *,
    proposal_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    account_email: str,
    parent_version_id: UUID | None,
) -> ResumeVersion:
    proposal = await get_owned_proposal(
        db,
        proposal_id=proposal_id,
        institution_id=institution_id,
        user_id=user_id,
    )
    if proposal.status != ProposalStatus.ACCEPTED.value:
        raise ProposalValidationError("Accept the proposal before creating a resume version")
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == user_id,
            StudentProfile.institution_id == institution_id,
        )
    )
    if profile is None or not profile.full_name:
        raise ProposalValidationError("Complete the reviewed profile before creating a resume")
    if parent_version_id:
        parent = await db.scalar(
            select(ResumeVersion.id).where(
                ResumeVersion.id == parent_version_id,
                ResumeVersion.user_id == user_id,
                ResumeVersion.institution_id == institution_id,
            )
        )
        if parent is None:
            raise ProposalValidationError("Parent resume version not found")
    education = (
        await db.scalars(
            select(StudentEducation)
            .where(StudentEducation.profile_id == profile.id)
            .order_by(StudentEducation.graduation_year.desc())
        )
    ).all()
    draft = ResumeDraft.model_validate(proposal.edited_content or proposal.generated_content)
    summary = draft.professional_summary.text if draft.professional_summary else ""
    content = ResumeContent(
        full_name=profile.full_name,
        email=account_email,
        phone=profile.phone,
        github_url=profile.external_links.get("github"),
        portfolio_url=profile.external_links.get("portfolio"),
        summary=summary,
        skills=[claim.text for claim in draft.skills],
        projects=[claim.text for claim in draft.project_bullets],
        education=[claim.text for claim in draft.education]
        or [
            (
                f"{item.degree}, {item.branch} — {item.institution}; "
                f"{item.graduation_year}; {item.score} {item.score_scale}"
            )
            for item in education
        ],
        experience=[claim.text for claim in draft.experience_bullets],
    )
    return await create_generated_version(
        db,
        user_id=user_id,
        institution_id=institution_id,
        content=content,
        store=build_object_store(get_settings()),
        settings=get_settings(),
        parent_version_id=parent_version_id,
        purpose_role_id=proposal.purpose_role_id,
        artifact_id=str(proposal.id),
        generated_provenance={
            "proposal_id": str(proposal.id),
            "evidence_digest": proposal.evidence_digest,
            "provider": proposal.provider_name,
            "model": proposal.model_version,
            "prompt_version": proposal.prompt_version,
        },
    )
