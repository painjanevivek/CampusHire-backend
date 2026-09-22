from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.auth import Institution, User
from app.models.engagement import RoadmapTemplate
from app.models.experience import CorrectionRequest, ReviewedPreparationMapping
from app.models.profile import StudentProfile
from app.models.recruitment import (
    Application,
    ApplicationStatusEvent,
    PlacementDrive,
    PlacementRole,
)
from app.models.resume import ResumeSuggestion, ResumeVersion
from app.modules.experience.schemas import (
    ApplicationQueueItem,
    ApplicationQueuePage,
    Metric,
    PreparationEvidence,
    PreparationResponse,
    ReportDefinitionMetadata,
    ReportResponse,
)
from app.modules.experience.service import ExperienceError, utc
from app.modules.outcomes.service import active_metric_definition, outcome_totals


def application_filters(
    institution_id: UUID, drive_id: UUID | None, start_at: datetime | None, end_at: datetime | None
) -> list[ColumnElement[bool]]:
    filters = [Application.institution_id == institution_id]
    if drive_id:
        filters.append(
            Application.role_id.in_(
                select(PlacementRole.id).where(
                    PlacementRole.drive_id == drive_id,
                    PlacementRole.institution_id == institution_id,
                )
            )
        )
    if start_at:
        filters.append(Application.created_at >= start_at)
    if end_at:
        filters.append(Application.created_at < end_at)
    return filters


async def review_queue(
    db: AsyncSession,
    institution_id: UUID,
    *,
    page: int = 1,
    page_size: int = 25,
    application_status: str | None = None,
    drive_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    requests: str | None = None,
    q: str | None = None,
    review_pending: bool = False,
    actor_user_id: UUID | None = None,
    actor_role: str | None = None,
    work_view: str | None = None,
) -> ApplicationQueuePage:
    filters = application_filters(institution_id, drive_id, start_at, end_at)
    if review_pending:
        filters.append(Application.status.in_(["submitted", "under_review"]))
    if application_status:
        filters.append(Application.status == application_status)
    if actor_role == "tnp_reviewer" and actor_user_id is not None:
        filters.append(Application.assignee_user_id == actor_user_id)
    elif work_view == "my_work" and actor_user_id is not None:
        filters.append(Application.assignee_user_id == actor_user_id)
    elif work_view == "unassigned":
        filters.append(Application.assignee_user_id.is_(None))
    elif work_view == "overdue":
        filters.extend(
            (
                Application.review_due_at.is_not(None),
                Application.review_due_at < datetime.now(UTC),
                Application.status.not_in(("offered", "rejected", "withdrawn")),
            )
        )
    if requests:
        request_filter = [
            CorrectionRequest.status
            == ("awaiting_review" if requests == "awaiting_review" else "open")
        ]
        if requests == "overdue":
            request_filter.append(CorrectionRequest.deadline_at < datetime.now(UTC))
        filters.append(
            Application.id.in_(select(CorrectionRequest.application_id).where(*request_filter))
        )
    if q:
        filters.append(
            func.lower(func.coalesce(StudentProfile.full_name, User.email)).contains(
                q.lower(), autoescape=True
            )
        )
    base = (
        select(
            Application.id,
            Application.status,
            Application.revision,
            Application.assignee_user_id,
            Application.review_due_at,
            Application.assignment_revision,
            Application.created_at,
            Application.role_snapshot,
            User.email,
            StudentProfile.full_name,
        )
        .join(User, User.id == Application.student_user_id)
        .outerjoin(
            StudentProfile,
            and_(
                StudentProfile.user_id == User.id, StudentProfile.institution_id == institution_id
            ),
        )
        .where(*filters)
    )
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    rows = (
        await db.execute(
            base.order_by(Application.created_at.desc(), Application.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    ids = [row.id for row in rows]
    counts = (
        {
            (row.application_id, row.status): row.count
            for row in (
                await db.execute(
                    select(
                        CorrectionRequest.application_id,
                        CorrectionRequest.status,
                        func.count().label("count"),
                    )
                    .where(
                        CorrectionRequest.application_id.in_(ids),
                        CorrectionRequest.institution_id == institution_id,
                    )
                    .group_by(CorrectionRequest.application_id, CorrectionRequest.status)
                )
            ).all()
        }
        if ids
        else {}
    )
    return ApplicationQueuePage(
        page=page,
        page_size=page_size,
        total=total,
        items=[
            ApplicationQueueItem(
                id=row.id,
                status=row.status,
                revision=row.revision,
                assignee_user_id=row.assignee_user_id,
                review_due_at=row.review_due_at,
                assignment_revision=row.assignment_revision,
                due_state=(
                    "complete"
                    if row.status in {"offered", "rejected", "withdrawn"}
                    else "unassigned"
                    if row.assignee_user_id is None
                    else "overdue"
                    if row.review_due_at is not None and row.review_due_at < datetime.now(UTC)
                    else "due_soon"
                    if row.review_due_at is not None
                    and row.review_due_at - datetime.now(UTC) <= timedelta(hours=24)
                    else "on_track"
                ),
                student_name=row.full_name or row.email,
                role_title=str(row.role_snapshot.get("title", "Role")),
                company_name=str(row.role_snapshot.get("company_name", "Company")),
                created_at=row.created_at,
                open_requests=counts.get((row.id, "open"), 0),
                awaiting_review=counts.get((row.id, "awaiting_review"), 0),
            )
            for row in rows
        ],
    )


async def operational_report(
    db: AsyncSession,
    institution_id: UUID,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    drive_id: UUID | None = None,
) -> ReportResponse:
    end = utc(end_at) if end_at else datetime.now(UTC)
    start = utc(start_at) if start_at else end - timedelta(days=30)
    if start >= end or end - start > timedelta(days=366):
        raise ExperienceError("report_date_range_invalid")
    filters = application_filters(institution_id, drive_id, start, end)
    app_ids = select(Application.id).where(*filters)
    distribution = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(Application.status, func.count())
                .where(*filters)
                .group_by(Application.status)
            )
        ).all()
    }
    sample = sum(distribution.values())
    params = {"start_at": start.isoformat(), "end_at": end.isoformat()}
    if drive_id:
        params["drive_id"] = str(drive_id)
    base = "/admin/applications?" + urlencode(params)
    metrics = [
        Metric(
            key="awaiting_review",
            label="Applications awaiting review",
            value=sum(distribution.get(s, 0) for s in ["submitted", "under_review"]),
            sample_size=sample,
            explanation=(
                "Submitted or under-review applications submitted within the reporting interval."
            ),
            href=base + "&review_pending=true",
        )
    ]
    for request_state in ("open", "overdue"):
        conditions = [
            CorrectionRequest.application_id.in_(app_ids),
            CorrectionRequest.status == "open",
        ]
        if request_state == "overdue":
            conditions.append(CorrectionRequest.deadline_at < datetime.now(UTC))
        count = int(
            await db.scalar(select(func.count()).select_from(CorrectionRequest).where(*conditions))
            or 0
        )
        metrics.append(
            Metric(
                key=f"requests_{request_state}",
                label=f"{request_state.title()} correction requests",
                value=count,
                sample_size=sample,
                explanation=(
                    "Request count for applications submitted within the reporting interval; "
                    "an application may have several requests."
                ),
                href=base + f"&requests={request_state}",
            )
        )
    first_change = (
        select(
            ApplicationStatusEvent.application_id,
            func.min(ApplicationStatusEvent.created_at).label("changed_at"),
        )
        .where(
            ApplicationStatusEvent.from_status == "submitted",
            ApplicationStatusEvent.to_status != "submitted",
        )
        .group_by(ApplicationStatusEvent.application_id)
        .subquery()
    )
    duration = func.extract("epoch", first_change.c.changed_at) - func.extract(
        "epoch", Application.created_at
    )
    turnaround = (
        await db.execute(
            select(func.avg(duration), func.count())
            .select_from(Application)
            .join(first_change, first_change.c.application_id == Application.id)
            .where(*filters)
        )
    ).one()
    metrics.append(
        Metric(
            key="turnaround",
            label="Average first review turnaround (hours)",
            value=round(float(turnaround[0]) / 3600, 2) if turnaround[0] is not None else None,
            sample_size=int(turnaround[1]),
            explanation=(
                "Submission to first recorded departure from submitted, including withdrawal; "
                "excludes applications with no departure."
            ),
            href=base,
        )
    )
    for status, count in sorted(distribution.items()):
        metrics.append(
            Metric(
                key=f"status_{status}",
                label=status.replace("_", " ").title(),
                value=count,
                sample_size=sample,
                explanation=(
                    "Current status of applications submitted within the reporting interval."
                ),
                href=base + "&application_status=" + status,
            )
        )
    outcome_summary = await outcome_totals(db, institution_id, start_at=start, end_at=end)
    for outcome_state, outcome_counts in (
        ("provisional", outcome_summary.provisional),
        ("verified", outcome_summary.verified),
    ):
        for event_type, count in sorted(outcome_counts.items()):
            metrics.append(
                Metric(
                    key=f"outcome_{event_type}_{outcome_state}",
                    label=(
                        f"{event_type.replace('_', ' ').title()} "
                        f"({outcome_state})"
                    ),
                    value=count,
                    sample_size=count,
                    explanation=(
                        "Current, non-superseded outcome events recorded within the interval. "
                        "Only a distinct verified joining event contributes to verified joining."
                    ),
                    href=(
                        "/tnp/reports?outcome_type="
                        + event_type
                        + "&outcome_state="
                        + outcome_state
                    ),
                )
            )
    now = datetime.now(UTC)
    drive_conditions = [
        PlacementDrive.institution_id == institution_id,
        PlacementDrive.status == "published",
        PlacementDrive.deadline_at >= now,
        PlacementDrive.deadline_at <= now + timedelta(days=7),
    ]
    if drive_id:
        drive_conditions.append(PlacementDrive.id == drive_id)
    closing = int(
        await db.scalar(select(func.count()).select_from(PlacementDrive).where(*drive_conditions))
        or 0
    )
    metrics.append(
        Metric(
            key="closing_drives",
            label="Drives closing within seven days",
            value=closing,
            sample_size=closing,
            explanation=(
                "Published drives with deadlines within seven days from now; "
                "independent of the application interval."
            ),
            href="/admin/drives?"
            + urlencode(
                {
                    "closing_within_days": "7",
                    "deadline_from": now.isoformat(),
                    "deadline_to": (now + timedelta(days=7)).isoformat(),
                }
            )
            + (f"&drive_id={drive_id}" if drive_id else ""),
        )
    )
    institution = await db.get(Institution, institution_id)
    definition = await active_metric_definition(db, "placement_outcomes", end)
    return ReportResponse(
        start_at=start,
        end_at=end,
        timezone=institution.timezone if institution else "UTC",
        definition=ReportDefinitionMetadata(
            code="placement_outcomes",
            version=definition.version if definition else None,
            status=definition.status if definition else "unconfigured",
            effective_at=definition.effective_at if definition else None,
            frozen_at=end,
        ),
        metrics=metrics,
    )


async def preparation(
    db: AsyncSession,
    institution_id: UUID,
    student_id: UUID,
    role_id: UUID,
    resume_id: UUID | None = None,
) -> PreparationResponse:
    from app.modules.recruitment.service import get_opportunity

    role = await get_opportunity(db, institution_id, student_id, role_id)
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == student_id, StudentProfile.institution_id == institution_id
        )
    )
    resume_query = select(ResumeVersion).where(
        ResumeVersion.user_id == student_id,
        ResumeVersion.institution_id == institution_id,
        ResumeVersion.status == "completed",
        ResumeVersion.scan_status == "clean",
    )
    if resume_id:
        resume_query = resume_query.where(ResumeVersion.id == resume_id)
    resume = await db.scalar(resume_query.order_by(ResumeVersion.created_at.desc()).limit(1))
    if resume_id and resume is None:
        raise ExperienceError("reviewed_resume_not_found")
    skills = {str(item.get("name", "")).casefold() for item in profile.skills} if profile else set()
    if resume:
        for item in resume.extracted_data.get("skills", []):
            skills.add(
                (str(item.get("name", "")) if isinstance(item, dict) else str(item)).casefold()
            )
    evidence = [
        PreparationEvidence(
            requirement=skill,
            demonstrated=skill.casefold() in skills,
            evidence="Recorded in your profile or reviewed resume."
            if skill.casefold() in skills
            else "Not demonstrated in your profile or reviewed resume.",
        )
        for skill in role.skills
    ]
    suggestions = (
        (
            await db.scalars(
                select(ResumeSuggestion)
                .where(ResumeSuggestion.resume_version_id == resume.id)
                .order_by(ResumeSuggestion.created_at)
                .limit(50)
            )
        ).all()
        if resume
        else []
    )
    institution = await db.get(Institution, institution_id)
    activities: list[dict[str, str]] = []
    if institution and institution.roadmaps_enabled:
        requirements = {item.strip().casefold() for item in [*role.skills, *role.requirements]}
        mappings = (
            await db.execute(
                select(ReviewedPreparationMapping, RoadmapTemplate)
                .join(RoadmapTemplate, RoadmapTemplate.id == ReviewedPreparationMapping.template_id)
                .where(
                    ReviewedPreparationMapping.institution_id == institution_id,
                    ReviewedPreparationMapping.status == "approved",
                    func.lower(ReviewedPreparationMapping.requirement).in_(requirements),
                    RoadmapTemplate.status == "approved",
                )
                .order_by(ReviewedPreparationMapping.requirement, ReviewedPreparationMapping.id)
                .limit(50)
            )
        ).all()
        for mapping, template in mappings:
            node = next(
                (node for node in template.nodes if node.get("key") == mapping.node_key), None
            )
            if node:
                activities.append(
                    {
                        "requirement": mapping.requirement,
                        "title": str(node["title"]),
                        "completion": str(node["completion"]),
                        "template": template.title,
                        "template_version": str(template.version),
                        "node_key": mapping.node_key,
                        "reviewed_at": mapping.reviewed_at.isoformat(),
                    }
                )
    return PreparationResponse(
        role_id=role.id,
        role_title=role.title,
        source_resume_version_id=resume.id if resume else None,
        source_profile_revision=profile.revision if profile else None,
        evidence=evidence,
        requirements=role.requirements,
        mapping_status="Activities from explicitly reviewed requirement mappings."
        if activities
        else "No approved requirement-to-roadmap mapping is available for this role.",
        activities=activities,
        roadmap_href="/roadmap",
        guidance_stale=bool(
            resume and profile and utc(profile.updated_at) > utc(resume.created_at)
        ),
        suggestions=[
            {
                "id": str(s.id),
                "original": s.original_text,
                "proposed": s.proposed_text,
                "reason": s.rationale,
                "status": s.status,
            }
            for s in suggestions
        ],
    )
