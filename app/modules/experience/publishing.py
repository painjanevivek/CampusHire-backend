"""Read-only publication checklist; the existing mutations remain the final authority."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recruitment import (
    Company,
    EligibilityRuleSet,
    PlacementDrive,
    PlacementRole,
    RoleApplicationForm,
)
from app.modules.experience.service import ExperienceError, utc
from app.modules.recruitment.schemas import DriveUpdate


class PublishRolePreview(BaseModel):
    id: UUID
    visible_on_publish: bool
    title: str
    description: str
    location: str
    work_mode: str
    salary_display: str | None
    requirements: list[str]
    rules: list[dict[str, object]]
    form_questions: list[dict[str, object]]
    pending_changes: dict[str, object]


class PublishPreview(BaseModel):
    drive_id: UUID
    title: str
    company_name: str
    opens_at: datetime
    deadline_at: datetime
    blockers: list[str]
    roles: list[PublishRolePreview]
    pending_changes: dict[str, object]
    completed_steps: list[int]


async def publication_preview(
    db: AsyncSession, institution_id: UUID, drive_id: UUID
) -> PublishPreview:
    drive = await db.scalar(
        select(PlacementDrive).where(
            PlacementDrive.id == drive_id, PlacementDrive.institution_id == institution_id
        )
    )
    if drive is None:
        raise ExperienceError("drive_not_found")
    changes = DriveUpdate.model_validate(drive.pending_changes).model_dump(exclude_unset=True)
    company = await db.scalar(
        select(Company).where(
            Company.id == changes.get("company_id", drive.company_id),
            Company.institution_id == institution_id,
        )
    )
    roles = (
        await db.scalars(
            select(PlacementRole)
            .where(PlacementRole.drive_id == drive.id)
            .order_by(PlacementRole.created_at)
        )
    ).all()
    rule_rows = (
        await db.scalars(
            select(EligibilityRuleSet)
            .where(EligibilityRuleSet.role_id.in_([r.id for r in roles]))
            .order_by(EligibilityRuleSet.version.desc())
        )
    ).all()
    forms = (
        await db.scalars(
            select(RoleApplicationForm)
            .where(
                RoleApplicationForm.role_id.in_([r.id for r in roles]),
                RoleApplicationForm.status == "published",
            )
            .order_by(RoleApplicationForm.version.desc())
        )
    ).all()
    blockers: list[str] = []
    opens = changes.get("opens_at", drive.opens_at)
    deadline = changes.get("deadline_at", drive.deadline_at)
    if drive.status not in {"draft", "published"}:
        blockers.append("Only a draft or published drive can be published or updated.")
    if company is None or company.status == "archived":
        blockers.append("Choose an active institution company.")
    if utc(opens) >= utc(deadline):
        blockers.append("The opening time must be before the deadline.")
    if utc(deadline) <= datetime.now(UTC):
        blockers.append("The application deadline has elapsed.")
    if not roles or (drive.status == "draft" and not any(r.status == "published" for r in roles)):
        blockers.append("Publish at least one role with a published eligibility version.")
    previews = []
    for role in roles:
        available = [
            r
            for r in rule_rows
            if r.role_id == role.id
            and r.status
            in ({"draft", "published"} if drive.status == "published" else {"published"})
        ]
        rule = available[0] if available else None
        form = next((f for f in forms if f.role_id == role.id), None)
        visible = drive.status == "published" or role.status == "published"
        if rule is None and visible:
            blockers.append(f"{role.title}: publish or stage a valid eligibility rule version.")
        values = {
            key: getattr(role, key)
            for key in (
                "title",
                "description",
                "location",
                "work_mode",
                "salary_display",
                "requirements",
            )
        }
        values.update({key: value for key, value in role.pending_changes.items() if key in values})
        previews.append(
            PublishRolePreview(
                id=role.id,
                visible_on_publish=visible,
                **values,
                rules=list(rule.rules) if rule else [],
                form_questions=list(form.questions) if form else [],
                pending_changes=dict(role.pending_changes),
            )
        )
    return PublishPreview(
        drive_id=drive.id,
        title=str(changes.get("title", drive.title)),
        company_name=company.name if company else "Unavailable",
        opens_at=opens,
        deadline_at=deadline,
        blockers=blockers,
        roles=previews,
        pending_changes=dict(drive.pending_changes),
        completed_steps=(
            ([1] if company and company.status != "archived" else [])
            + ([2] if roles else [])
            + (
                [3]
                if any(r.visible_on_publish for r in previews)
                and all(r.rules for r in previews if r.visible_on_publish)
                else []
            )
            + ([4] if utc(opens) < utc(deadline) and utc(deadline) > datetime.now(UTC) else [])
            + ([5] if not blockers else [])
        ),
    )
