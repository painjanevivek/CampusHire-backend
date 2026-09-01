import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from anyio import to_thread
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.workflows.policy_explanation import PolicyChunk, policy_graph
from app.core.config import get_settings
from app.models.intelligence import (
    PolicyDocument,
    ReviewStatus,
    RoleExtractionProposal,
    SemanticMatchEvidence,
)
from app.models.profile import StudentProfile
from app.models.recruitment import PlacementRole, PublicationStatus
from app.models.resume import ResumeStatus, ResumeVersion, ScanStatus
from app.modules.intelligence.schemas import (
    ExtractionCreate,
    ExtractionResponse,
    ExtractionReview,
    PolicyAnswer,
    PolicyCreate,
    PolicyQuestion,
    PolicyResponse,
    PolicyReview,
    SemanticMatchResponse,
)
from app.modules.matching.scoring import score_match


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]: ...


class IntelligenceError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _fingerprint(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _profile_projection(
    profile: StudentProfile, resume: ResumeVersion
) -> tuple[str, set[str], float]:
    """Project only placement evidence; names, contact data, PRN and links are excluded."""
    skills = {
        str(item.get("name", "")).strip()
        for item in profile.skills
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    }
    data = resume.extracted_data if isinstance(resume.extracted_data, dict) else {}
    safe_resume = {key: data.get(key) for key in ("summary", "skills", "projects", "experience")}
    projects = safe_resume.get("projects")
    project_evidence = min(1.0, len(projects) / 2) if isinstance(projects, list) else 0.0
    projection = {
        "department": profile.department,
        "target_roles": profile.target_roles,
        "skills": sorted(skills),
        "resume_evidence": safe_resume,
    }
    return json.dumps(projection, sort_keys=True, default=str), skills, project_evidence


def _role_projection(role: PlacementRole) -> str:
    return json.dumps(
        {
            "title": role.title,
            "description": role.description,
            "skills": role.skills,
            "requirements": role.requirements,
        },
        sort_keys=True,
    )


def _match_response(item: SemanticMatchEvidence) -> SemanticMatchResponse:
    return SemanticMatchResponse(
        status=item.status,
        score=item.score,
        components={key: float(value) for key, value in item.components.items()},
        explanation=item.explanation,
        embedding_model=item.embedding_model,
        embedding_version=item.embedding_version,
        scoring_version=item.scoring_version,
        source_resume_version_id=item.resume_version_id,
        source_profile_revision=item.profile_revision,
        safe_error_code=item.safe_error_code,
        evaluated_at=item.created_at,
    )


async def semantic_match(
    db: AsyncSession,
    *,
    institution_id: UUID,
    student_user_id: UUID,
    role_id: UUID,
    embedder: Embedder | None,
) -> SemanticMatchResponse:
    role = await db.scalar(
        select(PlacementRole).where(
            PlacementRole.id == role_id,
            PlacementRole.institution_id == institution_id,
            PlacementRole.status == PublicationStatus.PUBLISHED.value,
        )
    )
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == student_user_id,
            StudentProfile.institution_id == institution_id,
        )
    )
    resume = await db.scalar(
        select(ResumeVersion)
        .where(
            ResumeVersion.user_id == student_user_id,
            ResumeVersion.institution_id == institution_id,
            ResumeVersion.status == ResumeStatus.COMPLETED.value,
            ResumeVersion.scan_status == ScanStatus.CLEAN.value,
        )
        .order_by(ResumeVersion.version_number.desc(), ResumeVersion.created_at.desc())
    )
    if role is None:
        raise IntelligenceError("opportunity_not_found")
    settings = get_settings()
    if profile is None or resume is None:
        return SemanticMatchResponse(
            status="unavailable",
            score=None,
            components={},
            explanation=["Complete a reviewed profile and resume before calculating relevance."],
            embedding_model=settings.gemini_embedding_model,
            embedding_version="v1",
            scoring_version="match-v1",
            source_resume_version_id=resume.id if resume else None,
            source_profile_revision=profile.revision if profile else None,
            safe_error_code="match_inputs_incomplete",
        )

    student_text, student_skills, project_evidence = _profile_projection(profile, resume)
    role_text = _role_projection(role)
    fingerprint = _fingerprint(
        {
            "institution": institution_id,
            "student": student_user_id,
            "role": role.id,
            "role_updated": role.updated_at,
            "resume": resume.id,
            "profile_revision": profile.revision,
            "embedding_model": settings.gemini_embedding_model,
            "embedding_version": "v1",
            "scoring_version": "match-v1",
        }
    )
    existing = await db.scalar(
        select(SemanticMatchEvidence).where(
            SemanticMatchEvidence.institution_id == institution_id,
            SemanticMatchEvidence.fingerprint == fingerprint,
        )
    )
    if existing is not None:
        return _match_response(existing)

    status = "available"
    score: int | None = None
    components: dict[str, float] = {}
    explanation: list[str] = []
    safe_error_code: str | None = None
    if embedder is None:
        status = "unavailable"
        safe_error_code = "semantic_provider_unavailable"
        explanation = [
            "Skills matching is temporarily unavailable. Your eligibility has not changed."
        ]
    else:
        try:
            student_vector, role_vector = await to_thread.run_sync(
                lambda: (embedder.embed(student_text), embedder.embed(role_text))
            )
            result = score_match(
                student_vector,
                role_vector,
                student_skills,
                set(role.skills),
                project_evidence,
            )
            score = result.score
            components = {
                "semantic_similarity": result.semantic,
                "skill_coverage": result.skill_coverage,
                "project_evidence": result.project_evidence,
            }
            explanation = [
                f"{round(result.skill_coverage * 100)}% of published role skills are represented.",
                "Project details and skills similarity are checked separately "
                "to this relevance score.",
                "This score never changes your rule-based eligibility.",
            ]
        except Exception:
            status = "unavailable"
            safe_error_code = "semantic_provider_unavailable"
            explanation = [
                "Skills matching is temporarily unavailable. Your eligibility has not changed."
            ]

    evidence = SemanticMatchEvidence(
        institution_id=institution_id,
        student_user_id=student_user_id,
        role_id=role.id,
        resume_version_id=resume.id,
        profile_revision=profile.revision,
        fingerprint=fingerprint,
        status=status,
        score=score,
        components=components,
        explanation=explanation,
        embedding_model=settings.gemini_embedding_model,
        embedding_version="v1",
        scoring_version="match-v1",
        safe_error_code=safe_error_code,
        created_at=_now(),
    )
    db.add(evidence)
    await db.flush()
    return _match_response(evidence)


def _policy_response(item: PolicyDocument) -> PolicyResponse:
    return PolicyResponse.model_validate(item, from_attributes=True)


async def list_policies(db: AsyncSession, institution_id: UUID) -> list[PolicyResponse]:
    items = (
        await db.scalars(
            select(PolicyDocument)
            .where(PolicyDocument.institution_id == institution_id)
            .order_by(PolicyDocument.created_at.desc())
        )
    ).all()
    return [_policy_response(item) for item in items]


async def create_policy(
    db: AsyncSession, institution_id: UUID, actor_id: UUID, payload: PolicyCreate
) -> PolicyDocument:
    version = (
        await db.scalar(
            select(func.max(PolicyDocument.version)).where(
                PolicyDocument.institution_id == institution_id,
                func.lower(PolicyDocument.title) == payload.title.strip().lower(),
            )
        )
        or 0
    ) + 1
    item = PolicyDocument(
        institution_id=institution_id,
        title=payload.title.strip(),
        version=version,
        source_reference=payload.source_reference.strip(),
        sections=[section.model_dump() for section in payload.sections],
        created_by_user_id=actor_id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


async def review_policy(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    policy_id: UUID,
    payload: PolicyReview,
) -> PolicyDocument:
    item = await db.scalar(
        select(PolicyDocument).where(
            PolicyDocument.id == policy_id,
            PolicyDocument.institution_id == institution_id,
        )
    )
    if item is None:
        raise IntelligenceError("policy_not_found")
    if payload.action in {"approve", "reject"} and item.status != ReviewStatus.DRAFT.value:
        raise IntelligenceError("policy_review_already_final")
    if payload.action == "retire" and item.status != ReviewStatus.APPROVED.value:
        raise IntelligenceError("policy_not_approved")
    if payload.action == "approve":
        previous = (
            await db.scalars(
                select(PolicyDocument).where(
                    PolicyDocument.institution_id == institution_id,
                    func.lower(PolicyDocument.title) == item.title.lower(),
                    PolicyDocument.status == ReviewStatus.APPROVED.value,
                )
            )
        ).all()
        for old in previous:
            old.status = ReviewStatus.RETIRED.value
        item.status = ReviewStatus.APPROVED.value
        item.approved_at = _now()
    else:
        item.status = payload.action + "ed" if payload.action == "reject" else "retired"
    item.reviewed_by_user_id = actor_id
    item.review_reason = payload.reason
    await db.flush()
    await db.refresh(item)
    return item


async def answer_policy_question(
    db: AsyncSession, institution_id: UUID, payload: PolicyQuestion
) -> PolicyAnswer:
    policies = (
        await db.scalars(
            select(PolicyDocument)
            .where(
                PolicyDocument.institution_id == institution_id,
                PolicyDocument.status == ReviewStatus.APPROVED.value,
            )
            .order_by(PolicyDocument.approved_at.desc())
        )
    ).all()
    chunks: list[PolicyChunk] = []
    source_by_label: dict[str, PolicyDocument] = {}
    for policy in policies:
        for section in policy.sections:
            label = f"{policy.title} v{policy.version} · {section['section']}"
            chunks.append(
                {
                    "text": str(section["text"]),
                    "section": label,
                    "page": int(section["page"]),
                    "approved": True,
                }
            )
            source_by_label[label] = policy
    result = policy_graph.invoke(
        {
            "question": payload.question,
            "chunks": chunks,
            "citations": [],
            "answer": "",
            "iterations": 0,
        }
    )
    citations = [str(item) for item in result.get("citations", [])]
    matched = next(
        (
            policy
            for label, policy in source_by_label.items()
            if any(label in citation for citation in citations)
        ),
        None,
    )
    return PolicyAnswer(
        answer=str(result.get("answer", "Answer not found in the approved policy.")),
        citations=citations,
        policy_id=matched.id if matched else None,
        policy_version=matched.version if matched else None,
        grounded=bool(citations),
    )


def _extraction_response(item: RoleExtractionProposal) -> ExtractionResponse:
    return ExtractionResponse.model_validate(item, from_attributes=True)


async def create_extraction(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    role_id: UUID,
    payload: ExtractionCreate,
) -> RoleExtractionProposal:
    role = await db.scalar(
        select(PlacementRole).where(
            PlacementRole.id == role_id,
            PlacementRole.institution_id == institution_id,
            PlacementRole.status == PublicationStatus.DRAFT.value,
        )
    )
    if role is None:
        raise IntelligenceError("draft_role_not_found")
    lines = [
        re.sub(r"^[\s•*\-\d.)]+", "", line).strip() for line in payload.source_text.splitlines()
    ]
    requirements = [line for line in lines if 8 <= len(line) <= 300][:20]
    glossary = {
        "python",
        "java",
        "react",
        "typescript",
        "sql",
        "fastapi",
        "next.js",
        "aws",
        "docker",
    }
    words = {
        word.casefold() for word in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]*", payload.source_text)
    }
    skills = sorted(glossary & words)
    item = RoleExtractionProposal(
        institution_id=institution_id,
        role_id=role_id,
        source_text_hash=_fingerprint(payload.source_text),
        proposed_requirements=requirements,
        proposed_skills=skills,
        provider_name="bounded-parser",
        model_version="deterministic-v1",
        prompt_version="role-extraction-v1",
        created_by_user_id=actor_id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


async def list_extractions(
    db: AsyncSession, institution_id: UUID, role_id: UUID
) -> list[ExtractionResponse]:
    items = (
        await db.scalars(
            select(RoleExtractionProposal)
            .where(
                RoleExtractionProposal.institution_id == institution_id,
                RoleExtractionProposal.role_id == role_id,
            )
            .order_by(RoleExtractionProposal.created_at.desc())
        )
    ).all()
    return [_extraction_response(item) for item in items]


async def review_extraction(
    db: AsyncSession,
    institution_id: UUID,
    actor_id: UUID,
    proposal_id: UUID,
    payload: ExtractionReview,
) -> RoleExtractionProposal:
    item = await db.scalar(
        select(RoleExtractionProposal).where(
            RoleExtractionProposal.id == proposal_id,
            RoleExtractionProposal.institution_id == institution_id,
        )
    )
    if item is None:
        raise IntelligenceError("extraction_not_found")
    if item.status != ReviewStatus.DRAFT.value:
        raise IntelligenceError("extraction_review_already_final")
    role = await db.scalar(
        select(PlacementRole).where(
            PlacementRole.id == item.role_id,
            PlacementRole.institution_id == institution_id,
            PlacementRole.status == PublicationStatus.DRAFT.value,
        )
    )
    if role is None:
        raise IntelligenceError("draft_role_not_found")
    if payload.action == "approve":
        role.requirements = payload.requirements or item.proposed_requirements
        role.skills = payload.skills or item.proposed_skills
        item.status = ReviewStatus.APPROVED.value
    else:
        item.status = ReviewStatus.REJECTED.value
    item.reviewed_by_user_id = actor_id
    item.review_reason = payload.reason
    item.reviewed_at = _now()
    await db.flush()
    await db.refresh(item)
    return item
