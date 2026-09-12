import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from anyio import to_thread
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts import RESUME_CONTENT_V1
from app.ai.providers.base import StructuredGenerator
from app.core.config import get_settings
from app.models.generative_ai import (
    AiAcceptedFieldProvenance,
    AiGenerationProposal,
    ProposalStatus,
)
from app.models.onboarding import (
    InstitutionFeatureFlags,
    StudentCertification,
    StudentEducation,
    StudentExperience,
    StudentProject,
)
from app.models.profile import StudentProfile
from app.models.recruitment import PlacementRole, PublicationStatus
from app.modules.audit.service import record_audit_event
from app.modules.generative.schemas import EvidenceReference, ProposalResponse, ResumeDraft


class GenerationUnavailableError(Exception):
    pass


class ProposalConflictError(Exception):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision


class ProposalValidationError(Exception):
    pass


async def require_capability(db: AsyncSession, institution_id: UUID, capability: str) -> None:
    settings = get_settings()
    globally_enabled = bool(getattr(settings, capability, False))
    flags = await db.get(InstitutionFeatureFlags, institution_id)
    tenant_enabled = bool(flags and getattr(flags, capability, False))
    if not globally_enabled or not tenant_enabled:
        raise GenerationUnavailableError("capability_disabled")


async def ensure_generation_budget(
    db: AsyncSession, *, institution_id: UUID, prompt: str
) -> None:
    settings = get_settings()
    if (
        settings.ai_per_tenant_monthly_budget_cents <= 0
        or settings.ai_input_cost_cents_per_million_tokens <= 0
        or settings.ai_output_cost_cents_per_million_tokens <= 0
    ):
        raise GenerationUnavailableError("budget_not_configured")
    # Serialize budget admission on the tenant's feature row. All generation
    # paths require this row before reaching the provider, so the lock prevents
    # concurrent requests from spending against the same usage snapshot.
    await db.execute(
        select(InstitutionFeatureFlags.institution_id)
        .where(InstitutionFeatureFlags.institution_id == institution_id)
        .with_for_update()
    )
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    used_input, used_output = (
        await db.execute(
            select(
                func.coalesce(func.sum(AiGenerationProposal.input_tokens), 0),
                func.coalesce(func.sum(AiGenerationProposal.output_tokens), 0),
            ).where(
                AiGenerationProposal.institution_id == institution_id,
                AiGenerationProposal.created_at >= month_start,
            )
        )
    ).one()
    projected_input = max(1, len(prompt) // 4)
    projected_cost = (
        (int(used_input) + projected_input)
        * settings.ai_input_cost_cents_per_million_tokens
        + (int(used_output) + settings.ai_max_output_tokens)
        * settings.ai_output_cost_cents_per_million_tokens
    ) / 1_000_000
    if projected_cost > settings.ai_per_tenant_monthly_budget_cents:
        raise GenerationUnavailableError("tenant_budget_exhausted")


async def collect_resume_evidence(
    db: AsyncSession, *, institution_id: UUID, user_id: UUID
) -> list[EvidenceReference]:
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == user_id,
            StudentProfile.institution_id == institution_id,
        )
    )
    if profile is None:
        return []
    education = (
        await db.scalars(select(StudentEducation).where(StudentEducation.profile_id == profile.id))
    ).all()
    experience = (
        await db.scalars(
            select(StudentExperience).where(StudentExperience.profile_id == profile.id)
        )
    ).all()
    projects = (
        await db.scalars(select(StudentProject).where(StudentProject.profile_id == profile.id))
    ).all()
    certifications = (
        await db.scalars(
            select(StudentCertification).where(StudentCertification.profile_id == profile.id)
        )
    ).all()
    evidence: list[EvidenceReference] = []
    for education_item in education:
        evidence.append(
            EvidenceReference(
                evidence_id=f"education:{education_item.id}",
                kind="education",
                label=f"{education_item.degree} — {education_item.institution}",
                facts=(
                    f"{education_item.qualification_level}; {education_item.degree}; "
                    f"{education_item.branch}; {education_item.institution}; "
                    f"{education_item.start_year or 'unspecified'}–"
                    f"{education_item.graduation_year}; score {education_item.score} "
                    f"{education_item.score_scale}; active backlogs "
                    f"{education_item.active_backlogs}"
                ),
            )
        )
    for experience_item in experience:
        evidence.append(
            EvidenceReference(
                evidence_id=f"experience:{experience_item.id}",
                kind="experience",
                label=f"{experience_item.title} — {experience_item.organization}",
                facts=(
                    f"{experience_item.title} at {experience_item.organization}; "
                    f"{experience_item.start_date} to {experience_item.end_date or 'present'}; "
                    + "; ".join(experience_item.responsibilities)
                ),
            )
        )
    for project_item in projects:
        evidence.append(
            EvidenceReference(
                evidence_id=f"project:{project_item.id}",
                kind="project",
                label=project_item.title,
                facts=(
                    f"{project_item.title}; {project_item.description}; technologies: "
                    f"{', '.join(project_item.technologies)}; outcomes: "
                    f"{'; '.join(project_item.outcomes)}"
                ),
            )
        )
    for certification_item in certifications:
        evidence.append(
            EvidenceReference(
                evidence_id=f"certification:{certification_item.id}",
                kind="certification",
                label=certification_item.name,
                facts=(
                    f"{certification_item.name}; issuer {certification_item.issuer}; "
                    f"issued {certification_item.issued_on or 'unspecified'}"
                ),
            )
        )
    for index, skill_item in enumerate(profile.skills):
        if isinstance(skill_item, dict) and skill_item.get("name"):
            name = str(skill_item["name"])
            evidence.append(
                EvidenceReference(
                    evidence_id=f"profile:{profile.id}:skill:{index}",
                    kind="skill",
                    label=name,
                    facts=f"Reviewed profile skill: {name}",
                )
            )
    return evidence


def _content_claims(content: ResumeDraft) -> list[tuple[str, Any]]:
    claims: list[tuple[str, Any]] = []
    if content.professional_summary:
        claims.append(("professional_summary", content.professional_summary))
    for field in ("education", "project_bullets", "experience_bullets", "skills"):
        claims.extend(
            (f"{field}.{index}", claim) for index, claim in enumerate(getattr(content, field))
        )
    return claims


_GROUNDING_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "profile",
    "project",
    "reviewed",
    "skill",
    "skills",
    "that",
    "the",
    "to",
    "using",
    "with",
}
_GROUNDING_ALIASES = {
    "built": "build",
    "created": "build",
    "developed": "build",
    "implemented": "build",
    "leading": "lead",
    "led": "lead",
    "managed": "lead",
    "managing": "lead",
    "optimized": "improve",
    "optimizing": "improve",
}


def _grounding_terms(value: str) -> set[str]:
    terms = set(re.findall(r"[a-z][a-z0-9+#.-]{1,}", value.casefold()))
    return {
        _GROUNDING_ALIASES.get(term, term)
        for term in terms
        if term not in _GROUNDING_STOPWORDS
    }


def validate_grounding(content: ResumeDraft, evidence: list[EvidenceReference]) -> None:
    evidence_map = {item.evidence_id: item.facts for item in evidence}
    unsupported_markers = {
        "approved",
        "award",
        "certified",
        "increased",
        "million",
        "published",
        "reduced",
        "shortlisted",
        "billion",
    }
    for field_path, claim in _content_claims(content):
        if any(evidence_id not in evidence_map for evidence_id in claim.evidence_ids):
            raise ProposalValidationError(f"Unsupported evidence reference in {field_path}")
        source = " ".join(
            evidence_map[evidence_id] for evidence_id in claim.evidence_ids
        ).casefold()
        text = claim.text.casefold()
        if not (_grounding_terms(text) & _grounding_terms(source)):
            raise ProposalValidationError(f"Claim is not grounded in cited evidence: {field_path}")
        unsupported_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?\b", text)) - set(
            re.findall(r"\b\d+(?:\.\d+)?%?\b", source)
        )
        if unsupported_numbers:
            raise ProposalValidationError(f"Invented metric in {field_path}")
        if any(marker in text and marker not in source for marker in unsupported_markers):
            raise ProposalValidationError(f"Unsupported achievement in {field_path}")


def _proposal_response(item: AiGenerationProposal) -> ProposalResponse:
    content = item.edited_content or item.generated_content
    return ProposalResponse(
        id=item.id,
        capability=item.capability,
        purpose_role_id=item.purpose_role_id,
        status=item.status,
        revision=item.revision,
        content=ResumeDraft.model_validate(content),
        evidence_references=[
            EvidenceReference.model_validate(reference) for reference in item.evidence_references
        ],
        evidence_digest=item.evidence_digest,
        provider_name=item.provider_name,
        model_version=item.model_version,
        prompt_version=item.prompt_version,
        created_at=item.created_at,
        accepted_at=item.accepted_at,
        rejected_at=item.rejected_at,
    )


async def create_resume_proposal(
    db: AsyncSession,
    *,
    institution_id: UUID,
    user_id: UUID,
    selected_evidence_ids: list[str],
    purpose_role_id: UUID | None,
    generator: StructuredGenerator | None,
    correlation_id: str | None,
) -> ProposalResponse:
    await require_capability(db, institution_id, "ai_generation")
    if generator is None:
        raise GenerationUnavailableError("provider_unavailable")
    evidence = await collect_resume_evidence(db, institution_id=institution_id, user_id=user_id)
    if selected_evidence_ids:
        requested = set(selected_evidence_ids)
        evidence = [item for item in evidence if item.evidence_id in requested]
        if {item.evidence_id for item in evidence} != requested:
            raise ProposalValidationError("One or more evidence records are unavailable")
    if not evidence:
        raise ProposalValidationError("Add reviewed profile evidence before generating content")
    role_context: dict[str, object] | None = None
    if purpose_role_id:
        role = await db.scalar(
            select(PlacementRole).where(
                PlacementRole.id == purpose_role_id,
                PlacementRole.institution_id == institution_id,
                PlacementRole.status == PublicationStatus.PUBLISHED.value,
            )
        )
        if role is None:
            raise ProposalValidationError("The selected role is unavailable")
        role_context = {
            "title": role.title,
            "description": role.description,
            "skills": role.skills,
            "note": "Role context may guide emphasis but is not student evidence.",
        }
    evidence_payload = [item.model_dump(mode="json") for item in evidence]
    canonical = json.dumps(evidence_payload, sort_keys=True, separators=(",", ":"))
    evidence_digest = hashlib.sha256(canonical.encode()).hexdigest()
    prompt = (
        f"{RESUME_CONTENT_V1.instructions}\n\n"
        f"ROLE_CONTEXT={json.dumps(role_context, sort_keys=True)}\n"
        f"EVIDENCE={canonical}"
    )
    await ensure_generation_budget(db, institution_id=institution_id, prompt=prompt)
    last_error: Exception | None = None
    result = None
    for _attempt in range(2):
        try:
            generated = await to_thread.run_sync(
                lambda: generator.generate_structured(
                    prompt=prompt, response_schema=ResumeDraft.model_json_schema()
                )
            )
            draft = ResumeDraft.model_validate(generated.content)
            validate_grounding(draft, evidence)
            result = (generated, draft)
            break
        except (RuntimeError, ValueError, ValidationError, ProposalValidationError) as error:
            last_error = error
    if result is None:
        raise GenerationUnavailableError("generation_validation_failed") from last_error
    generated, draft = result
    proposal = AiGenerationProposal(
        institution_id=institution_id,
        user_id=user_id,
        purpose_role_id=purpose_role_id,
        capability="resume_content",
        generated_content=draft.model_dump(mode="json"),
        evidence_references=evidence_payload,
        evidence_digest=evidence_digest,
        provider_name=generated.provider_name,
        model_version=generated.model_version,
        prompt_version=RESUME_CONTENT_V1.version,
        latency_ms=generated.latency_ms,
        input_tokens=generated.input_tokens,
        output_tokens=generated.output_tokens,
    )
    db.add(proposal)
    await db.flush()
    record_audit_event(
        db,
        actor_user_id=user_id,
        institution_id=institution_id,
        event_type="ai.proposal.created",
        resource_type="ai_generation_proposal",
        resource_id=str(proposal.id),
        correlation_id=correlation_id,
        details={"capability": proposal.capability, "prompt_version": proposal.prompt_version},
    )
    await db.commit()
    await db.refresh(proposal)
    return _proposal_response(proposal)


async def get_owned_proposal(
    db: AsyncSession, *, proposal_id: UUID, institution_id: UUID, user_id: UUID, lock: bool = False
) -> AiGenerationProposal:
    query = select(AiGenerationProposal).where(
        AiGenerationProposal.id == proposal_id,
        AiGenerationProposal.institution_id == institution_id,
        AiGenerationProposal.user_id == user_id,
    )
    if lock:
        query = query.with_for_update()
    item = await db.scalar(query)
    if item is None:
        raise ProposalValidationError("Proposal not found")
    return item


async def read_proposal(
    db: AsyncSession, *, proposal_id: UUID, institution_id: UUID, user_id: UUID
) -> ProposalResponse:
    return _proposal_response(
        await get_owned_proposal(
            db, proposal_id=proposal_id, institution_id=institution_id, user_id=user_id
        )
    )


async def list_owned_proposals(
    db: AsyncSession, *, institution_id: UUID, user_id: UUID
) -> list[ProposalResponse]:
    records = await db.scalars(
        select(AiGenerationProposal)
        .where(
            AiGenerationProposal.institution_id == institution_id,
            AiGenerationProposal.user_id == user_id,
        )
        .order_by(AiGenerationProposal.created_at.desc())
        .limit(100)
    )
    return [_proposal_response(item) for item in records.all()]


async def edit_proposal(
    db: AsyncSession,
    *,
    proposal_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    expected_revision: int,
    content: ResumeDraft,
) -> ProposalResponse:
    item = await get_owned_proposal(
        db,
        proposal_id=proposal_id,
        institution_id=institution_id,
        user_id=user_id,
        lock=True,
    )
    if item.revision != expected_revision:
        raise ProposalConflictError(item.revision)
    if item.status != ProposalStatus.DRAFT.value:
        raise ProposalValidationError("Only draft proposals can be edited")
    evidence = [EvidenceReference.model_validate(value) for value in item.evidence_references]
    validate_grounding(content, evidence)
    item.edited_content = content.model_dump(mode="json")
    item.revision += 1
    await db.commit()
    await db.refresh(item)
    return _proposal_response(item)


async def decide_proposal(
    db: AsyncSession,
    *,
    proposal_id: UUID,
    institution_id: UUID,
    user_id: UUID,
    expected_revision: int,
    accept: bool,
    correlation_id: str | None,
) -> ProposalResponse:
    item = await get_owned_proposal(
        db,
        proposal_id=proposal_id,
        institution_id=institution_id,
        user_id=user_id,
        lock=True,
    )
    if item.revision != expected_revision:
        raise ProposalConflictError(item.revision)
    if item.status != ProposalStatus.DRAFT.value:
        raise ProposalValidationError("Proposal has already been decided")
    content = ResumeDraft.model_validate(item.edited_content or item.generated_content)
    evidence = [EvidenceReference.model_validate(value) for value in item.evidence_references]
    validate_grounding(content, evidence)
    now = datetime.now(UTC)
    item.status = ProposalStatus.ACCEPTED.value if accept else ProposalStatus.REJECTED.value
    item.accepted_at = now if accept else None
    item.rejected_at = None if accept else now
    item.revision += 1
    if accept:
        db.add_all(
            [
                AiAcceptedFieldProvenance(
                    proposal_id=item.id,
                    institution_id=institution_id,
                    user_id=user_id,
                    field_path=field_path,
                    provider_name=item.provider_name,
                    model_version=item.model_version,
                    prompt_version=item.prompt_version,
                    evidence_digest=item.evidence_digest,
                )
                for field_path, _claim in _content_claims(content)
            ]
        )
    record_audit_event(
        db,
        actor_user_id=user_id,
        institution_id=institution_id,
        event_type=f"ai.proposal.{item.status}",
        resource_type="ai_generation_proposal",
        resource_id=str(item.id),
        correlation_id=correlation_id,
    )
    await db.commit()
    await db.refresh(item)
    return _proposal_response(item)
