import re
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.auth import Institution, User
from app.models.engagement import (
    InAppNotification,
    RoadmapProgress,
    RoadmapTemplate,
    StudentRoadmap,
)
from app.models.intelligence import SemanticMatchEvidence
from app.models.onboarding import StudentProject
from app.models.profile import StudentProfile
from app.models.recruitment import Application, PlacementRole
from app.models.resume import ResumeSource, ResumeStatus, ResumeVersion, ScanStatus
from app.modules.engagement.schemas import (
    ActivationStage,
    DashboardEvidence,
    DashboardOpportunity,
    DashboardReadinessSummary,
    DashboardResponse,
    NextAction,
    NotificationCreate,
    NotificationPage,
    NotificationResponse,
    RoadmapAvailabilityResponse,
    RoadmapMilestonePreview,
    RoadmapNodeResponse,
    RoadmapProgressUpdate,
    RoadmapResponse,
    RoadmapTaskResponse,
    RoadmapTemplateResponse,
)
from app.modules.intelligence.service import match_fingerprint, reviewed_resume_evidence
from app.modules.matching.scoring import profile_compatibility
from app.modules.notifications.domain import safe_deep_link
from app.modules.recruitment.service import list_opportunities
from app.modules.roadmaps.graph import CURATED_ROADMAPS, RoadmapNode, next_nodes, validate_dag

READINESS_POLICY_VERSION = "readiness-v2"

# Only unambiguous, reviewed title equivalents receive an automatic match.
# All other ambitions can use the approved catalog as a self-selected foundation.
ROADMAP_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "software-developer": ("software engineer", "software development engineer", "sde"),
    "frontend-developer": ("front end developer", "front end engineer", "frontend engineer"),
    "backend-developer": ("back end developer", "back end engineer", "backend engineer"),
    "full-stack-developer": ("full stack developer", "full stack engineer"),
    "mobile-application-developer": ("mobile developer", "android developer", "ios developer"),
    "data-analyst": ("business data analyst",),
    "machine-learning-engineer": ("ml engineer", "machine learning developer"),
    "ai-engineer": ("artificial intelligence engineer", "generative ai engineer"),
}


def _normalized_role(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


class EngagementError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _template_id(slug: str, version: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"campushire:roadmap:{slug}:{version}")


async def ensure_templates(db: AsyncSession) -> None:
    existing = set((await db.execute(select(RoadmapTemplate.slug, RoadmapTemplate.version))).all())
    for slug, (title, summary, nodes) in CURATED_ROADMAPS.items():
        if (slug, 2) in existing:
            continue
        validate_dag(nodes)
        db.add(
            RoadmapTemplate(
                id=_template_id(slug, 2),
                slug=slug,
                title=title,
                version=2,
                summary=summary,
                nodes=[
                    {
                        "key": node.key,
                        "title": node.title,
                        "completion": node.completion,
                        "prerequisites": list(node.prerequisites),
                        "signals": list(node.signals),
                    }
                    for node in nodes
                ],
                status="approved",
                approved_at=_now(),
            )
        )
    await db.flush()


async def list_templates(db: AsyncSession) -> list[RoadmapTemplateResponse]:
    await ensure_templates(db)
    all_items = (
        await db.scalars(
            select(RoadmapTemplate)
            .where(RoadmapTemplate.status == "approved")
            .order_by(RoadmapTemplate.title, RoadmapTemplate.version.desc())
        )
    ).all()
    items = list({item.slug: item for item in reversed(all_items)}.values())
    items.sort(key=lambda item: item.title)
    return [
        RoadmapTemplateResponse(
            id=item.id,
            slug=item.slug,
            title=item.title,
            version=item.version,
            summary=item.summary,
            node_count=len(item.nodes),
            milestones=[
                RoadmapMilestonePreview(
                    title=str(node["title"]), completion=str(node["completion"])
                )
                for node in item.nodes
            ],
        )
        for item in items
    ]


async def roadmap_availability(
    db: AsyncSession, institution_id: UUID, student_user_id: UUID
) -> RoadmapAvailabilityResponse:
    institution = await db.get(Institution, institution_id)
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.institution_id == institution_id,
            StudentProfile.user_id == student_user_id,
        )
    )
    provider_status = "available" if get_settings().gemini_api_key else "unavailable"
    if institution is None or not institution.roadmaps_enabled:
        return RoadmapAvailabilityResponse(
            status="institution_restriction",
            reason="Your institution has not enabled curated roadmaps for this membership.",
            guidance_provider_status=provider_status,
            templates=[],
        )
    if profile is None or not profile.target_roles:
        return RoadmapAvailabilityResponse(
            status="no_target_role",
            reason="Choose a target role in your profile before selecting a roadmap.",
            guidance_provider_status=provider_status,
            templates=[],
        )
    templates = await list_templates(db)
    targets = {_normalized_role(str(value)) for value in profile.target_roles}
    mapped = [
        item
        for item in templates
        if targets
        & {
            _normalized_role(item.title),
            *(_normalized_role(alias) for alias in ROADMAP_ROLE_ALIASES.get(item.slug, ())),
        }
    ]
    if not templates:
        return RoadmapAvailabilityResponse(
            status="no_approved_template",
            reason=(
                "No curated roadmap is available yet. Your target role is saved in your profile."
            ),
            target_roles=profile.target_roles,
            guidance_provider_status=provider_status,
            templates=[],
        )
    if not mapped:
        return RoadmapAvailabilityResponse(
            status="available",
            reason=(
                "There is no direct curated path for your target role yet. Choose a curated "
                "foundation path that feels closest to your goal; it is not an exact match."
            ),
            match_basis="self_selected",
            target_roles=profile.target_roles,
            guidance_provider_status=provider_status,
            templates=templates,
        )
    return RoadmapAvailabilityResponse(
        status="available",
        reason="These curated paths match the target roles saved in your profile.",
        match_basis="target_role",
        target_roles=profile.target_roles,
        guidance_provider_status=provider_status,
        templates=mapped,
    )


def _node_models(template: RoadmapTemplate) -> list[RoadmapNode]:
    nodes = [
        RoadmapNode(
            key=str(item["key"]),
            title=str(item["title"]),
            completion=str(item["completion"]),
            prerequisites=tuple(str(value) for value in item.get("prerequisites", [])),
            signals=tuple(str(value) for value in item.get("signals", [])),
        )
        for item in template.nodes
    ]
    validate_dag(nodes)
    return nodes


def _node_guidance(
    node: RoadmapNode, *, slug: str, skills: list[str], projects: list[StudentProject]
) -> tuple[str, str, list[RoadmapTaskResponse], list[str]]:
    recorded = [
        skill
        for skill in skills
        if len(skill) >= 3
        and any(signal in skill.casefold() or skill.casefold() in signal for signal in node.signals)
    ]
    for source_project in projects:
        for technology in source_project.technologies or []:
            value = str(technology).strip()
            if (
                len(value) >= 3
                and any(
                    signal in value.casefold() or value.casefold() in signal
                    for signal in node.signals
                )
                and value not in recorded
            ):
                recorded.append(value)
    project = projects[0] if projects else None
    if recorded:
        why = (
            f"Your profile or project lists {', '.join(recorded[:2])}. This is recorded "
            f"context, not verified proficiency. {node.completion}"
        )
    elif project:
        why = (
            f"Your {project.title} project is recorded, but related work for this step is "
            f"not recorded in your profile or project technologies. This is an evidence gap, "
            f"not a judgement of ability. {node.completion}"
        )
    else:
        why = (
            f"No related skill or project evidence is recorded yet. This is an evidence gap, "
            f"not a judgement of ability. {node.completion}"
        )
    practice = (
        f"Extend your existing {project.title} project and record exactly what you changed."
        if project
        else f"Create a small {node.title.casefold()} project and save an accurate work sample."
    )
    tasks = [
        RoadmapTaskResponse(
            title=f"Plan {node.title.casefold()}",
            detail="Define the scope, expected behavior, and what you will be able to show.",
        ),
        RoadmapTaskResponse(title="Build and test it", detail=node.completion),
        RoadmapTaskResponse(
            title="Explain your choices",
            detail="Record the result, tests, trade-offs, and your own contribution.",
        ),
    ]
    if slug == "backend-developer" and node.title == "Database design":
        tasks = [
            RoadmapTaskResponse(
                title="Design the schema",
                detail="Define your data models and relationships for PostgreSQL.",
            ),
            RoadmapTaskResponse(
                title="Add migrations and tests",
                detail="Make schema changes repeatable and test the data flow.",
            ),
            RoadmapTaskResponse(
                title="Document trade-offs",
                detail="Explain your design decisions and alternatives you considered.",
            ),
        ]
    return why, practice, tasks, recorded


async def roadmap_response(
    db: AsyncSession, roadmap: StudentRoadmap, template: RoadmapTemplate | None = None
) -> RoadmapResponse:
    template = template or await db.get(RoadmapTemplate, roadmap.template_id)
    if template is None:
        raise EngagementError("roadmap_template_not_found")
    progress = (
        await db.scalars(
            select(RoadmapProgress).where(RoadmapProgress.student_roadmap_id == roadmap.id)
        )
    ).all()
    progress_by_key = {item.node_key: item for item in progress}
    completed = {item.node_key for item in progress if item.status == "completed"}
    nodes = _node_models(template)
    next_keys = {item.key for item in next_nodes(nodes, completed)}
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.institution_id == roadmap.institution_id,
            StudentProfile.user_id == roadmap.student_user_id,
        )
    )
    projects = (
        list(
            (
                await db.scalars(
                    select(StudentProject)
                    .where(StudentProject.profile_id == profile.id)
                    .order_by(StudentProject.created_at.desc())
                    .limit(5)
                )
            ).all()
        )
        if profile
        else []
    )
    skills = [
        str(skill.get("name", "")).strip()
        for skill in (profile.skills if profile else [])
        if isinstance(skill, dict) and str(skill.get("name", "")).strip()
    ]
    guidance = {
        node.key: _node_guidance(node, slug=template.slug, skills=skills, projects=projects)
        for node in nodes
    }
    return RoadmapResponse(
        id=roadmap.id,
        template_id=template.id,
        slug=template.slug,
        title=template.title,
        version=template.version,
        summary=template.summary,
        completed_count=len(completed),
        nodes=[
            RoadmapNodeResponse(
                key=node.key,
                title=node.title,
                completion=node.completion,
                prerequisites=list(node.prerequisites),
                state="completed"
                if node.key in completed
                else "next"
                if node.key in next_keys
                else "locked",
                evidence=progress_by_key[node.key].evidence if node.key in progress_by_key else {},
                why=guidance[node.key][0],
                practice=guidance[node.key][1],
                tasks=guidance[node.key][2],
                recorded_context=guidance[node.key][3],
            )
            for node in nodes
        ],
    )


async def current_roadmap(
    db: AsyncSession, institution_id: UUID, student_user_id: UUID
) -> RoadmapResponse | None:
    roadmap = await db.scalar(
        select(StudentRoadmap).where(
            StudentRoadmap.institution_id == institution_id,
            StudentRoadmap.student_user_id == student_user_id,
        )
    )
    return await roadmap_response(db, roadmap) if roadmap else None


async def select_roadmap(
    db: AsyncSession, institution_id: UUID, student_user_id: UUID, template_id: UUID
) -> RoadmapResponse:
    availability = await roadmap_availability(db, institution_id, student_user_id)
    if availability.status != "available":
        raise EngagementError(f"roadmap_{availability.status}")
    if template_id not in {item.id for item in availability.templates}:
        raise EngagementError("roadmap_template_not_available")
    await ensure_templates(db)
    template = await db.scalar(
        select(RoadmapTemplate).where(
            RoadmapTemplate.id == template_id, RoadmapTemplate.status == "approved"
        )
    )
    if template is None:
        raise EngagementError("roadmap_template_not_found")
    roadmap = await db.scalar(
        select(StudentRoadmap).where(StudentRoadmap.student_user_id == student_user_id)
    )
    if roadmap is None:
        roadmap = StudentRoadmap(
            institution_id=institution_id,
            student_user_id=student_user_id,
            template_id=template.id,
        )
        db.add(roadmap)
        await db.flush()
    elif roadmap.template_id != template.id:
        progress_count = await db.scalar(
            select(func.count())
            .select_from(RoadmapProgress)
            .where(RoadmapProgress.student_roadmap_id == roadmap.id)
        )
        if progress_count:
            raise EngagementError("roadmap_change_requires_progress_reset")
        roadmap.template_id = template.id
        await db.flush()
    return await roadmap_response(db, roadmap, template)


async def update_roadmap_progress(
    db: AsyncSession,
    institution_id: UUID,
    student_user_id: UUID,
    node_key: str,
    payload: RoadmapProgressUpdate,
) -> RoadmapResponse:
    roadmap = await db.scalar(
        select(StudentRoadmap).where(
            StudentRoadmap.institution_id == institution_id,
            StudentRoadmap.student_user_id == student_user_id,
        )
    )
    if roadmap is None:
        raise EngagementError("roadmap_not_selected")
    template = await db.get(RoadmapTemplate, roadmap.template_id)
    if template is None:
        raise EngagementError("roadmap_template_not_found")
    nodes = {node.key: node for node in _node_models(template)}
    node = nodes.get(node_key)
    if node is None:
        raise EngagementError("roadmap_node_not_found")
    progress = (
        await db.scalars(
            select(RoadmapProgress).where(RoadmapProgress.student_roadmap_id == roadmap.id)
        )
    ).all()
    completed = {item.node_key for item in progress if item.status == "completed"}
    if payload.completed and not set(node.prerequisites) <= completed:
        raise EngagementError("roadmap_prerequisites_incomplete")
    item = next((entry for entry in progress if entry.node_key == node_key), None)
    if item is None:
        item = RoadmapProgress(student_roadmap_id=roadmap.id, node_key=node_key)
        db.add(item)
    item.status = "completed" if payload.completed else "in_progress"
    item.evidence = {
        key: value
        for key, value in {
            "label": payload.evidence_label,
            "reference": payload.evidence_reference,
        }.items()
        if value
    }
    item.completed_at = _now() if payload.completed else None
    await db.flush()
    return await roadmap_response(db, roadmap, template)


def _notification_response(item: InAppNotification) -> NotificationResponse:
    return NotificationResponse.model_validate(item, from_attributes=True)


async def upsert_notification(
    db: AsyncSession,
    *,
    institution_id: UUID,
    recipient_user_id: UUID,
    event_key: str,
    title: str,
    body: str,
    deep_link: str,
    created_by_user_id: UUID | None,
) -> InAppNotification:
    safe_deep_link(deep_link)
    recipient = await db.scalar(
        select(User.id).where(
            User.id == recipient_user_id,
            User.institution_id == institution_id,
        )
    )
    if recipient is None:
        raise EngagementError("notification_recipient_not_found")
    existing = await db.scalar(
        select(InAppNotification).where(
            InAppNotification.recipient_user_id == recipient_user_id,
            InAppNotification.event_key == event_key,
        )
    )
    if existing is not None:
        return existing
    item = InAppNotification(
        institution_id=institution_id,
        recipient_user_id=recipient_user_id,
        event_key=event_key,
        title=title,
        body=body,
        deep_link=deep_link,
        created_by_user_id=created_by_user_id,
        created_at=_now(),
    )
    db.add(item)
    await db.flush()
    return item


async def publish_notification(
    db: AsyncSession, institution_id: UUID, actor_id: UUID, payload: NotificationCreate
) -> InAppNotification:
    return await upsert_notification(
        db,
        institution_id=institution_id,
        recipient_user_id=payload.recipient_user_id,
        event_key=payload.event_key,
        title=payload.title,
        body=payload.body,
        deep_link=payload.deep_link,
        created_by_user_id=actor_id,
    )


async def list_notifications(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID
) -> NotificationPage:
    filters = [InAppNotification.recipient_user_id == student_user_id]
    if institution_id is not None:
        filters.append(InAppNotification.institution_id == institution_id)
    items = (
        await db.scalars(
            select(InAppNotification)
            .where(*filters)
            .order_by(InAppNotification.created_at.desc())
            .limit(100)
        )
    ).all()
    from app.models.experience import CorrectionRequest

    request_ids = [item.related_request_id for item in items if item.related_request_id]
    open_ids = (
        set(
            (
                await db.scalars(
                    select(CorrectionRequest.id).where(
                        CorrectionRequest.id.in_(request_ids),
                        *(
                            [CorrectionRequest.institution_id == institution_id]
                            if institution_id is not None
                            else []
                        ),
                        CorrectionRequest.status == "open",
                    )
                )
            ).all()
        )
        if request_ids
        else set()
    )
    responses = [_notification_response(item) for item in items]
    for response in responses:
        if response.related_request_id:
            response.category = (
                "needs_action" if response.related_request_id in open_ids else "updates"
            )
    return NotificationPage(
        items=responses,
        unread_count=sum(item.read_at is None for item in items),
    )


async def mark_notification_read(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID, notification_id: UUID
) -> InAppNotification:
    filters = [
        InAppNotification.id == notification_id,
        InAppNotification.recipient_user_id == student_user_id,
    ]
    if institution_id is not None:
        filters.append(InAppNotification.institution_id == institution_id)
    item = await db.scalar(select(InAppNotification).where(*filters))
    if item is None:
        raise EngagementError("notification_not_found")
    item.read_at = item.read_at or _now()
    await db.flush()
    return item


async def dashboard(
    db: AsyncSession, institution_id: UUID, student_user_id: UUID
) -> DashboardResponse:
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == student_user_id,
            StudentProfile.institution_id == institution_id,
        )
    )
    user = await db.get(User, student_user_id)
    resumes = (
        await db.scalars(
            select(ResumeVersion)
            .where(
                ResumeVersion.user_id == student_user_id,
                ResumeVersion.institution_id == institution_id,
            )
            .order_by(ResumeVersion.created_at.desc())
        )
    ).all()
    reviewed = next(
        (
            item
            for item in resumes
            if item.status == ResumeStatus.COMPLETED.value
            and item.scan_status == ScanStatus.CLEAN.value
        ),
        None,
    )
    processing = any(item.status in {"queued", "processing"} for item in resumes)
    application_count = int(
        await db.scalar(
            select(func.count())
            .select_from(Application)
            .where(
                Application.institution_id == institution_id,
                Application.student_user_id == student_user_id,
            )
        )
        or 0
    )
    roadmap = await current_roadmap(db, institution_id, student_user_id)
    notices = await list_notifications(db, institution_id, student_user_id)
    opportunity_page = await list_opportunities(
        db,
        institution_id,
        student_user_id,
        query=None,
        location=None,
        work_mode=None,
        skill=None,
        saved_only=False,
        page=1,
        page_size=100,
        sort="applied",
    )
    eligible = [item for item in opportunity_page.items if item.eligibility.status == "eligible"][
        :3
    ]
    current_match_by_role: dict[UUID, SemanticMatchEvidence] = {}
    role_by_id: dict[UUID, PlacementRole] = {}
    generated_resume: ResumeVersion | None = None
    if eligible and profile:
        role_ids = [item.id for item in eligible]
        roles = (
            await db.scalars(
                select(PlacementRole).where(
                    PlacementRole.institution_id == institution_id,
                    PlacementRole.id.in_(role_ids),
                )
            )
        ).all()
        role_by_id = {role.id: role for role in roles}
        generated_resume = await db.scalar(
            select(ResumeVersion)
            .where(
                ResumeVersion.user_id == student_user_id,
                ResumeVersion.institution_id == institution_id,
                ResumeVersion.status == ResumeStatus.COMPLETED.value,
                ResumeVersion.scan_status == ScanStatus.CLEAN.value,
                ResumeVersion.source == ResumeSource.GENERATED.value,
            )
            .order_by(ResumeVersion.version_number.desc(), ResumeVersion.created_at.desc())
        )
        fingerprints = {
            role.id: match_fingerprint(
                institution_id=institution_id,
                student_user_id=student_user_id,
                role_id=role.id,
                role_updated_at=role.updated_at,
                resume_version_id=generated_resume.id if generated_resume else None,
                profile_revision=profile.revision,
                embedding_model=get_settings().gemini_embedding_model,
            )
            for role in roles
        }
        matches = (
            await db.scalars(
                select(SemanticMatchEvidence).where(
                    SemanticMatchEvidence.institution_id == institution_id,
                    SemanticMatchEvidence.student_user_id == student_user_id,
                    SemanticMatchEvidence.fingerprint.in_(list(fingerprints.values())),
                    SemanticMatchEvidence.status == "available",
                )
            )
        ).all()
        current_match_by_role = {
            match.role_id: match
            for match in matches
            if fingerprints.get(match.role_id) == match.fingerprint
        }

    profile_skills = {
        str(skill.get("name", "")).strip()
        for skill in (profile.skills if profile else [])
        if isinstance(skill, dict) and str(skill.get("name", "")).strip()
    }
    _, resume_skills = reviewed_resume_evidence(generated_resume)
    local_match_by_role = {
        role.id: profile_compatibility(
            student_skills=profile_skills,
            resume_skills=resume_skills,
            target_roles=profile.target_roles if profile else [],
            role_skills=role.skills,
            role_title=role.title,
        )
        for role in role_by_id.values()
    }

    identity_complete = bool(
        profile
        and profile.full_name
        and profile.department
        and profile.education
        and profile.target_roles
    )
    project_evidence = bool(
        profile
        and await db.scalar(
            select(StudentProject.id).where(StudentProject.profile_id == profile.id).limit(1)
        )
    )
    readiness_evidence = [identity_complete, project_evidence, roadmap is not None]
    if not identity_complete:
        action = NextAction(
            key="complete_profile",
            title="Complete your placement profile",
            description=(
                "Add the required education and target-role facts used by eligibility rules."
            ),
            reason=(
                "You can browse published roles now; missing facts may need review "
                "when checking eligibility."
            ),
            href="/onboarding",
            policy_version=READINESS_POLICY_VERSION,
            source_facts=["required_profile_facts_incomplete"],
            estimated_minutes=8,
            unlocks="More complete role-specific eligibility explanations",
            completion_criteria="Required identity, education, and target-role facts are saved.",
        )
    elif not project_evidence:
        action = NextAction(
            key="add_project_evidence",
            title="Add a project",
            description="Add a project you worked on to your student profile.",
            reason="Projects help explain your experience but do not gate opportunity browsing.",
            href="/onboarding",
            policy_version=READINESS_POLICY_VERSION,
            source_facts=["profile_project_missing"],
            estimated_minutes=12,
            unlocks="Clearer profile evidence",
            completion_criteria="One accurate project is saved to your profile.",
        )
    elif roadmap is None:
        action = NextAction(
            key="select_roadmap",
            title="Choose your career roadmap",
            description=("Select one reviewed path so CampusHire can show the next milestone."),
            reason="A reviewed path keeps suggestions focused and in the right order.",
            href="/roadmap",
            policy_version=READINESS_POLICY_VERSION,
            source_facts=["roadmap_not_selected"],
            estimated_minutes=3,
            unlocks="A prerequisite-aware next milestone",
            completion_criteria="One approved path mapped to your target role is selected.",
        )
    else:
        next_node = next((item for item in roadmap.nodes if item.state == "next"), None)
        action = NextAction(
            key="roadmap_milestone" if next_node else "browse_opportunities",
            title=next_node.title if next_node else "Review your eligible opportunities",
            description=next_node.completion
            if next_node
            else "Compare published roles and their formal requirements.",
            reason=(
                "Its prerequisites are complete and it is the first unfinished reviewed milestone."
                if next_node
                else "Your current roadmap is complete; eligibility is still checked for each role."
            ),
            href="/roadmap" if next_node else "/opportunities",
            policy_version=READINESS_POLICY_VERSION,
            source_facts=[f"roadmap:{roadmap.id}:v{roadmap.version}"],
            estimated_minutes=next_node and 20 or 5,
            unlocks=(
                "The next roadmap milestone" if next_node else "A confident application decision"
            ),
            completion_criteria=(
                next_node.completion
                if next_node
                else "Review one eligible role and its published requirements."
            ),
        )

    profile_minimum = bool(
        profile and profile.full_name and profile.department and profile.education
    )
    target_role = bool(profile and profile.target_roles)
    opportunities_unlocked = bool(profile and profile.prn)
    activation_facts = [
        (
            "account_activated",
            "Account activated",
            True,
            "/profile",
            1,
            "Your private student workspace",
        ),
        (
            "profile_minimum",
            "Profile minimum",
            profile_minimum,
            "/onboarding",
            8,
            "Eligibility-ready education facts",
        ),
        ("target_role", "Target role", target_role, "/onboarding", 2, "A relevant curated roadmap"),
        (
            "opportunities_unlocked",
            "Opportunities unlocked",
            opportunities_unlocked,
            "/opportunities",
            5,
            "Eligible roles published by your institution",
        ),
        (
            "first_application",
            "First application",
            application_count > 0,
            "/applications",
            5,
            "Application tracking and status history",
        ),
    ]
    first_incomplete = next(
        (index for index, item in enumerate(activation_facts) if not item[2]), None
    )
    activation = [
        ActivationStage(
            key=key,
            label=label,
            status="complete"
            if complete
            else "current"
            if index == first_incomplete
            else "upcoming",
            href=href,
            estimated_minutes=minutes,
            unlocks=unlocks,
        )
        for index, (key, label, complete, href, minutes, unlocks) in enumerate(activation_facts)
    ]

    state = "incomplete" if not identity_complete else "ready"
    if state == "ready" and any(
        item.eligibility.status == "needs_manual_review" for item in opportunity_page.items
    ):
        state = "manual-review"

    from app.models.auth import Institution
    from app.modules.experience.priorities import placement_actions

    action, upcoming = await placement_actions(
        db, institution_id, student_user_id, action, identity_complete, bool(reviewed), processing
    )
    institution = await db.get(Institution, institution_id)
    return DashboardResponse(
        upcoming=upcoming,
        institution_timezone=institution.timezone if institution else "Asia/Kolkata",
        student_name=(
            profile.full_name.split()[0]
            if profile and profile.full_name
            else user.email.split("@")[0]
            if user
            else "Student"
        ),
        readiness=DashboardReadinessSummary(
            policy_version=READINESS_POLICY_VERSION,
            completed_evidence=sum(readiness_evidence),
            total_evidence=len(readiness_evidence),
            required_complete=identity_complete,
        ),
        state=state,
        next_action=action,
        activation=activation,
        evidence=[
            DashboardEvidence(
                label="Required profile",
                value="Complete" if identity_complete else "Missing facts",
                status="verified" if identity_complete else "pending",
            ),
            DashboardEvidence(
                label="Project details",
                value="Attached" if project_evidence else "Missing",
                status="verified" if project_evidence else "pending",
            ),
            DashboardEvidence(
                label="Career roadmap",
                value=roadmap.title if roadmap else "Not selected",
                status="verified" if roadmap else "pending",
            ),
        ],
        opportunities=[
            DashboardOpportunity(
                id=item.id,
                company=item.company_name,
                drive_title=item.drive_title,
                role=item.title,
                location=f"{item.location} · {item.work_mode}",
                eligibility="Formally eligible",
                application_status=item.application_status,
                match=(
                    current_match_by_role[item.id].score
                    if item.id in current_match_by_role
                    else local_match_by_role.get(item.id)
                ),
                match_basis=(
                    "semantic"
                    if item.id in current_match_by_role
                    else "profile"
                    if local_match_by_role.get(item.id) is not None
                    else None
                ),
                href=f"/opportunities/{item.id}",
            )
            for item in eligible
        ],
        roadmap=roadmap,
        unread_notifications=notices.unread_count,
    )
