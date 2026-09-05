"""Deterministic placement priorities, computed using server time."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.experience import CorrectionRequest
from app.models.recruitment import Application, ApplicationDraft, PlacementDrive, PlacementRole
from app.modules.engagement.schemas import NextAction
from app.modules.experience.service import utc

ACTION_POLICY = "placement-actions-v2"


def action_sort_key(
    priority: int, deadline: datetime | None, created: datetime, identifier: str
) -> tuple[int, datetime, datetime, str]:
    return (
        priority,
        utc(deadline) if deadline else datetime.max.replace(tzinfo=UTC),
        utc(created),
        identifier,
    )


async def placement_actions(
    db: AsyncSession,
    institution_id: UUID,
    student_id: UUID,
    fallback: NextAction,
    profile_ready: bool,
    resume_ready: bool,
    processing: bool,
    now: datetime | None = None,
) -> tuple[NextAction, list[NextAction]]:
    from app.modules.recruitment.service import list_opportunities

    current = utc(now) if now else datetime.now(UTC)
    urgent = current + timedelta(hours=72)
    entries: list[tuple[tuple[int, datetime, datetime, str], NextAction]] = []

    def add(priority: int, item: NextAction, created: datetime, identifier: str) -> None:
        entries.append((action_sort_key(priority, item.deadline_at, created, identifier), item))

    requests = (
        await db.scalars(
            select(CorrectionRequest)
            .join(Application)
            .where(
                CorrectionRequest.institution_id == institution_id,
                Application.student_user_id == student_id,
                Application.institution_id == institution_id,
                CorrectionRequest.status == "open",
                Application.status.not_in(["offered", "rejected", "withdrawn"]),
            )
            .order_by(
                CorrectionRequest.deadline_at.asc().nullslast(),
                CorrectionRequest.created_at,
                CorrectionRequest.id,
            )
            .limit(6)
        )
    ).all()
    for item in requests:
        add(
            0 if item.deadline_at and utc(item.deadline_at) <= urgent else 2,
            NextAction(
                key=f"correction:{item.id}",
                category="correction",
                title="Respond to your placement team",
                description=item.instructions,
                reason="Your placement team needs additional information for this application.",
                href=f"/applications/{item.application_id}#request-{item.id}",
                deadline_at=item.deadline_at,
                policy_version=ACTION_POLICY,
                source_facts=[f"correction:{item.id}:v{item.revision}"],
                estimated_minutes=5,
                unlocks="Placement team review",
                completion_criteria="Send your response for review.",
            ),
            item.created_at,
            str(item.id),
        )
    drafts = (
        await db.execute(
            select(ApplicationDraft, PlacementRole.title, PlacementDrive.deadline_at)
            .join(PlacementRole, PlacementRole.id == ApplicationDraft.role_id)
            .join(PlacementDrive, PlacementDrive.id == PlacementRole.drive_id)
            .where(
                ApplicationDraft.institution_id == institution_id,
                ApplicationDraft.student_user_id == student_id,
                ApplicationDraft.submitted_application_id.is_(None),
                ApplicationDraft.expires_at > current,
                PlacementRole.status == "published",
                PlacementDrive.status == "published",
                PlacementDrive.opens_at <= current,
                PlacementDrive.deadline_at > current,
                PlacementDrive.deadline_at <= urgent,
                ~exists(
                    select(Application.id).where(
                        Application.role_id == ApplicationDraft.role_id,
                        Application.student_user_id == student_id,
                    )
                ),
            )
            .order_by(PlacementDrive.deadline_at, ApplicationDraft.created_at, ApplicationDraft.id)
            .limit(6)
        )
    ).all()
    for draft, title, deadline in drafts:
        destination = f"/opportunities/{draft.role_id}/apply"
        prerequisite = ""
        if not profile_ready:
            destination, prerequisite = (
                "/onboarding",
                "Complete your required profile details first. ",
            )
        elif not resume_ready:
            destination, prerequisite = "/resume", "Review a clean resume version first. "
        add(
            1,
            NextAction(
                key=f"draft:{draft.id}",
                category="application",
                deadline_at=deadline,
                title=f"Continue your {title} application",
                description=prerequisite + "Your saved draft is closing soon.",
                reason="This unsubmitted application closes within 72 hours.",
                href=destination,
                policy_version=ACTION_POLICY,
                source_facts=[f"draft:{draft.id}:v{draft.revision}"],
                estimated_minutes=5,
                unlocks="A submitted application",
                completion_criteria="Review the saved details and confirm the application.",
            ),
            draft.created_at,
            str(draft.id),
        )
    required = fallback.key in {"complete_profile", "review_resume"}
    fallback = fallback.model_copy(update={"policy_version": ACTION_POLICY})
    if fallback.key == "add_resume" and processing:
        fallback = fallback.model_copy(
            update={
                "key": "resume_processing",
                "title": "Check your resume processing",
                "description": "Your resume is being processed. You can continue browsing.",
                "reason": "The existing upload is still processing; another upload is not needed.",
                "completion_criteria": "Review the extracted details when processing finishes.",
            }
        )
    add(
        3 if required else 5 if fallback.key != "browse_opportunities" else 6,
        fallback,
        current,
        fallback.key,
    )
    saved = await list_opportunities(
        db,
        institution_id,
        student_id,
        query=None,
        location=None,
        work_mode=None,
        skill=None,
        saved_only=True,
        page=1,
        page_size=6,
        eligibility_status="eligible",
        deadline_within_days=3,
        sort="deadline",
        unapplied_only=True,
    )
    for opportunity in saved.items:
        if opportunity.application_id is not None:
            continue
        add(
            4,
            NextAction(
                key=f"saved:{opportunity.id}",
                category="opportunity",
                deadline_at=opportunity.deadline_at,
                title=f"Review {opportunity.title}",
                description=f"Your saved role at {opportunity.company_name} closes soon.",
                reason="You saved this eligible role and have not applied.",
                href=f"/opportunities/{opportunity.id}",
                policy_version=ACTION_POLICY,
                source_facts=[f"role:{opportunity.id}"],
                estimated_minutes=5,
                unlocks="An informed application",
                completion_criteria="Review the role and decide whether to apply.",
            ),
            opportunity.published_at or current,
            str(opportunity.id),
        )
    entries.sort(key=lambda pair: pair[0])
    return entries[0][1], [pair[1] for pair in entries[1:6]]
