from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.generative_ai import ProposalStatus
from app.models.onboarding import (
    StudentCertification,
    StudentEducation,
    StudentExperience,
    StudentProject,
)
from app.models.profile import StudentProfile
from app.models.resume import ResumeVersion
from app.modules.generative.schemas import EvidenceReference, ResumeDraft
from app.modules.generative.service import (
    ProposalValidationError,
    collect_resume_evidence,
    get_owned_proposal,
)
from app.modules.resumes.builder import ResumeContent
from app.modules.resumes.workflow import create_generated_version


def _score_text(score: object, scale: str) -> str:
    if score is None or str(score) == "":
        return ""
    if scale == "cgpa_10":
        return f"CGPA: {score}/10"
    if scale == "percentage":
        return f"Percentage: {score}%"
    return str(score)


def _education_text(item: StudentEducation | dict[str, object]) -> str:
    value = item if isinstance(item, dict) else vars(item)
    qualification = " ".join(
        str(value.get(field) or "").strip() for field in ("degree", "branch")
    ).strip()
    dates = "–".join(
        str(value.get(field)).strip()
        for field in ("start_year", "graduation_year")
        if value.get(field)
    )
    metadata = " · ".join(part for part in (str(value.get("institution") or ""), dates) if part)
    score = _score_text(value.get("score"), str(value.get("score_scale") or ""))
    return " — ".join(part for part in (qualification, metadata, score) if part)


def _claim_texts(draft: ResumeDraft, section: str, evidence_id: str) -> list[str]:
    claims = getattr(draft, section)
    return [claim.text for claim in claims if evidence_id in claim.evidence_ids]


def _validate_evidence_snapshot(
    original: list[dict[str, object]], current: list[EvidenceReference]
) -> None:
    current_by_id = {item.evidence_id: item for item in current}
    for value in original:
        selected = EvidenceReference.model_validate(value)
        if current_by_id.get(selected.evidence_id) != selected:
            raise ProposalValidationError(
                "The selected profile details changed. Generate and review a new proposal."
            )


def _resume_content_from_proposal(
    *,
    profile: StudentProfile,
    account_email: str,
    education: list[StudentEducation],
    projects: list[StudentProject],
    experience: list[StudentExperience],
    certifications: list[StudentCertification],
    evidence_ids: set[str],
    draft: ResumeDraft,
) -> ResumeContent:
    # Match the manual builder's profile-prefilled lines. AI supplies reviewed
    # wording, while titles, dates, links, and credentials come from profile facts.
    education_source: list[StudentEducation | dict[str, object]] = []
    if education:
        education_source.extend(education)
    else:
        education_source.extend(
            dict(record) for record in profile.education if isinstance(record, dict)
        )
    education_lines = []
    for item in education_source:
        item_id = item.get("id") if isinstance(item, dict) else item.id
        level = item.get("qualification_level") if isinstance(item, dict) else getattr(
            item, "qualification_level", "degree"
        )
        # Keep the degree as the standard resume baseline. School marks are
        # included only when the student selected that record as AI evidence.
        if level != "degree" and (not item_id or f"education:{item_id}" not in evidence_ids):
            continue
        line = _education_text(item)
        if item_id:
            line = " — ".join(
                [line, *_claim_texts(draft, "education", f"education:{item_id}")]
            )
        if line:
            education_lines.append(line)

    project_lines = []
    for project_item in projects:
        bullets = _claim_texts(draft, "project_bullets", f"project:{project_item.id}")
        if not bullets:
            continue
        technologies = ", ".join(project_item.technologies)
        project_lines.append(
            " — ".join(
                part
                for part in (
                    project_item.title,
                    *bullets,
                    f"Technologies: {technologies}" if technologies else "",
                    project_item.project_url or "",
                )
                if part
            )
        )

    experience_lines = []
    for experience_item in experience:
        bullets = _claim_texts(
            draft, "experience_bullets", f"experience:{experience_item.id}"
        )
        if not bullets:
            continue
        dates = "–".join(
            part
            for part in (
                str(experience_item.start_date) if experience_item.start_date else "",
                str(experience_item.end_date)
                if experience_item.end_date
                else "Present" if experience_item.is_current else "",
            )
            if part
        )
        experience_lines.append(
            " — ".join(
                part
                for part in (
                    experience_item.title,
                    " · ".join(
                        part for part in (experience_item.organization, dates) if part
                    ),
                    *bullets,
                )
                if part
            )
        )

    certification_lines = [
        " — ".join(
            part for part in (item.name, item.issuer, str(item.issued_on or "")) if part
        )
        for item in certifications
        if f"certification:{item.id}" in evidence_ids
    ]
    links = profile.external_links or {}
    if not education_lines:
        raise ProposalValidationError("Add education to your saved profile before creating a PDF")
    try:
        return ResumeContent(
            full_name=profile.full_name or "",
            email=account_email,
            phone=profile.phone,
            github_url=links.get("github"),
            linkedin_url=links.get("linkedin"),
            portfolio_url=links.get("portfolio"),
            summary=draft.professional_summary.text if draft.professional_summary else "",
            strengths=[claim.text for claim in draft.strengths],
            skills=[claim.text for claim in draft.skills],
            projects=project_lines,
            education=education_lines,
            experience=experience_lines,
            certifications=certification_lines,
        )
    except ValidationError as error:
        raise ProposalValidationError(
            "The reviewed details do not fit the resume fields. Create a shorter proposal "
            "or use the manual builder."
        ) from error


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
    current_evidence = await collect_resume_evidence(
        db, institution_id=institution_id, user_id=user_id
    )
    _validate_evidence_snapshot(proposal.evidence_references, current_evidence)
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
    projects = (
        await db.scalars(select(StudentProject).where(StudentProject.profile_id == profile.id))
    ).all()
    experience = (
        await db.scalars(
            select(StudentExperience).where(StudentExperience.profile_id == profile.id)
        )
    ).all()
    certifications = (
        await db.scalars(
            select(StudentCertification).where(StudentCertification.profile_id == profile.id)
        )
    ).all()
    draft = ResumeDraft.model_validate(proposal.edited_content or proposal.generated_content)
    content = _resume_content_from_proposal(
        profile=profile,
        account_email=account_email,
        education=list(education),
        projects=list(projects),
        experience=list(experience),
        certifications=list(certifications),
        evidence_ids={item["evidence_id"] for item in proposal.evidence_references},
        draft=draft,
    )
    return await create_generated_version(
        db,
        user_id=user_id,
        institution_id=institution_id,
        content=content,
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
