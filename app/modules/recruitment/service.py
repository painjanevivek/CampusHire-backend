import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import cast, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.auth import Institution, User
from app.models.intelligence import PolicyDocument, ReviewStatus, SemanticMatchEvidence
from app.models.profile import StudentProfile
from app.models.recruitment import (
    Application,
    ApplicationAppeal,
    ApplicationOverride,
    ApplicationStatusEvent,
    Company,
    EligibilityEvaluation,
    EligibilityRuleSet,
    PlacementDrive,
    PlacementRole,
    PublicationStatus,
    RuleSetStatus,
    SavedOpportunity,
)
from app.models.resume import ResumeStatus, ResumeVersion, ScanStatus
from app.modules.eligibility.engine import Rule, evaluate
from app.modules.recruitment.domain import ApplicationStatus, validate_transition
from app.modules.recruitment.schemas import (
    AdminApplicationPage,
    ApplicationAppealCreate,
    ApplicationAppealResolution,
    ApplicationAppealResponse,
    ApplicationCreate,
    ApplicationOverrideCreate,
    ApplicationResponse,
    ApplicationStatusUpdate,
    ApplicationWithdrawal,
    BulkApplicationPreviewItem,
    BulkApplicationPreviewResponse,
    BulkApplicationStatusRequest,
    CompanyCreate,
    CompanyResponse,
    CompanyUpdate,
    DriveCreate,
    DriveResponse,
    DriveUpdate,
    EligibilityResponse,
    OpportunityPage,
    OpportunityResponse,
    OverrideResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    RuleSetCreate,
    RuleSetResponse,
    StatusEventResponse,
)


class RecruitmentError(ValueError):
    pass


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _institution(institution_id: UUID | None) -> UUID:
    if institution_id is None:
        raise RecruitmentError("institution_context_required")
    return institution_id


def _skill_filter(skill: str) -> ColumnElement[bool]:
    """Match one complete skill without relying on invalid JSON string operators."""
    role_skills = (
        func.jsonb_array_elements_text(cast(PlacementRole.skills, JSONB))
        .table_valued("value")
        .alias("role_skill")
    )
    return exists(
        select(1)
        .select_from(role_skills)
        .where(func.lower(role_skills.c.value) == skill.strip().lower())
    )


def company_response(company: Company) -> CompanyResponse:
    return CompanyResponse(
        id=company.id,
        name=company.name,
        website_url=company.website_url,
        description=company.description,
        status=company.status,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


async def list_companies(db: AsyncSession, institution_id: UUID | None) -> list[CompanyResponse]:
    institution = _institution(institution_id)
    companies = (
        await db.scalars(
            select(Company).where(Company.institution_id == institution).order_by(Company.name)
        )
    ).all()
    return [company_response(item) for item in companies]


async def create_company(
    db: AsyncSession, institution_id: UUID | None, payload: CompanyCreate
) -> Company:
    institution = _institution(institution_id)
    duplicate = await db.scalar(
        select(Company.id).where(
            Company.institution_id == institution,
            func.lower(Company.name) == payload.name.strip().lower(),
        )
    )
    if duplicate:
        raise RecruitmentError("company_name_exists")
    company = Company(institution_id=institution, **payload.model_dump())
    db.add(company)
    await db.flush()
    await db.refresh(company)
    return company


async def update_company(
    db: AsyncSession,
    institution_id: UUID | None,
    company_id: UUID,
    payload: CompanyUpdate,
) -> Company:
    company = await db.scalar(
        select(Company).where(
            Company.id == company_id, Company.institution_id == _institution(institution_id)
        )
    )
    if company is None:
        raise RecruitmentError("company_not_found")
    if company.status == PublicationStatus.ARCHIVED.value:
        raise RecruitmentError("company_archived")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, key, value)
    await db.flush()
    await db.refresh(company)
    return company


async def drive_response(db: AsyncSession, drive: PlacementDrive) -> DriveResponse:
    company_name = await db.scalar(select(Company.name).where(Company.id == drive.company_id))
    roles = (
        await db.scalars(select(PlacementRole).where(PlacementRole.drive_id == drive.id))
    ).all()
    role_ids = [role.id for role in roles]
    has_draft_rules = bool(
        role_ids
        and await db.scalar(
            select(EligibilityRuleSet.id).where(
                EligibilityRuleSet.role_id.in_(role_ids),
                EligibilityRuleSet.status == RuleSetStatus.DRAFT.value,
            )
        )
    )
    has_pending_changes = drive.status == PublicationStatus.PUBLISHED.value and bool(
        drive.pending_changes
        or has_draft_rules
        or any(
            role.pending_changes or role.status == PublicationStatus.DRAFT.value for role in roles
        )
    )
    return DriveResponse(
        id=drive.id,
        company_id=drive.company_id,
        company_name=company_name or "Unknown company",
        title=drive.title,
        description=drive.description,
        location=drive.location,
        work_mode=drive.work_mode,
        opens_at=drive.opens_at,
        deadline_at=drive.deadline_at,
        status=drive.status,
        published_at=drive.published_at,
        created_at=drive.created_at,
        updated_at=drive.updated_at,
        role_count=len(roles),
        pending_changes=dict(drive.pending_changes),
        has_pending_changes=has_pending_changes,
    )


async def list_drives(db: AsyncSession, institution_id: UUID | None) -> list[DriveResponse]:
    drives = (
        await db.scalars(
            select(PlacementDrive)
            .where(PlacementDrive.institution_id == _institution(institution_id))
            .order_by(PlacementDrive.created_at.desc())
        )
    ).all()
    return [await drive_response(db, item) for item in drives]


async def create_drive(
    db: AsyncSession, institution_id: UUID | None, payload: DriveCreate
) -> PlacementDrive:
    institution = _institution(institution_id)
    company = await db.scalar(
        select(Company).where(
            Company.id == payload.company_id,
            Company.institution_id == institution,
            Company.status != PublicationStatus.ARCHIVED.value,
        )
    )
    if company is None:
        raise RecruitmentError("company_not_found")
    drive = PlacementDrive(institution_id=institution, **payload.model_dump())
    db.add(drive)
    await db.flush()
    await db.refresh(drive)
    return drive


async def _owned_drive(
    db: AsyncSession, institution_id: UUID | None, drive_id: UUID, *, lock: bool = False
) -> PlacementDrive:
    query = select(PlacementDrive).where(
        PlacementDrive.id == drive_id,
        PlacementDrive.institution_id == _institution(institution_id),
    )
    drive = await db.scalar(query.with_for_update() if lock else query)
    if drive is None:
        raise RecruitmentError("drive_not_found")
    return drive


async def update_drive(
    db: AsyncSession,
    institution_id: UUID | None,
    drive_id: UUID,
    payload: DriveUpdate,
) -> PlacementDrive:
    institution = _institution(institution_id)
    drive = await _owned_drive(db, institution, drive_id, lock=True)
    if drive.status not in {
        PublicationStatus.DRAFT.value,
        PublicationStatus.PUBLISHED.value,
    }:
        raise RecruitmentError("published_drive_is_immutable")
    pending = dict(drive.pending_changes)
    pending.update(payload.model_dump(mode="json", exclude_unset=True))
    values = DriveUpdate.model_validate(pending).model_dump(exclude_unset=True)
    company_id = values.get("company_id")
    if company_id is not None:
        company = await db.scalar(
            select(Company).where(
                Company.id == company_id,
                Company.institution_id == institution,
                Company.status != PublicationStatus.ARCHIVED.value,
            )
        )
        if company is None:
            raise RecruitmentError("company_not_found")
    opens_at = values.get("opens_at", drive.opens_at)
    deadline_at = values.get("deadline_at", drive.deadline_at)
    if _utc(opens_at) >= _utc(deadline_at):
        raise RecruitmentError("drive_window_invalid")
    if drive.status == PublicationStatus.PUBLISHED.value:
        drive.pending_changes = pending
    else:
        for key, value in values.items():
            setattr(drive, key, value)
    await db.flush()
    await db.refresh(drive)
    return drive


async def delete_drive(
    db: AsyncSession,
    institution_id: UUID | None,
    drive_id: UUID,
) -> PlacementDrive:
    drive = await _owned_drive(db, institution_id, drive_id, lock=True)
    if drive.status != PublicationStatus.DRAFT.value:
        raise RecruitmentError("published_drive_is_immutable")
    await db.delete(drive)
    await db.flush()
    return drive


async def transition_drive(
    db: AsyncSession, institution_id: UUID | None, drive_id: UUID, action: str
) -> PlacementDrive:
    drive = await _owned_drive(db, institution_id, drive_id, lock=True)
    now = datetime.now(UTC)
    if action == "publish":
        if drive.status != PublicationStatus.DRAFT.value:
            raise RecruitmentError("drive_publish_transition_invalid")
        published_roles = await db.scalar(
            select(func.count())
            .select_from(PlacementRole)
            .where(
                PlacementRole.drive_id == drive.id,
                PlacementRole.status == PublicationStatus.PUBLISHED.value,
            )
        )
        if not published_roles:
            raise RecruitmentError("drive_requires_published_role")
        if _utc(drive.deadline_at) <= now:
            raise RecruitmentError("drive_deadline_elapsed")
        drive.status = PublicationStatus.PUBLISHED.value
        drive.published_at = now
    elif action == "close":
        if drive.status != PublicationStatus.PUBLISHED.value:
            raise RecruitmentError("drive_close_transition_invalid")
        drive.status = PublicationStatus.CLOSED.value
        drive.closed_at = now
    elif action == "archive":
        if drive.status not in {PublicationStatus.CLOSED.value, PublicationStatus.DRAFT.value}:
            raise RecruitmentError("drive_archive_transition_invalid")
        drive.status = PublicationStatus.ARCHIVED.value
    else:
        raise RecruitmentError("drive_action_invalid")
    await db.flush()
    await db.refresh(drive)
    return drive


async def save_drive_changes(
    db: AsyncSession, institution_id: UUID | None, drive_id: UUID
) -> tuple[PlacementDrive, list[UUID]]:
    """Atomically activate all staged drive, role, and eligibility changes."""
    institution = _institution(institution_id)
    drive = await _owned_drive(db, institution, drive_id, lock=True)
    if drive.status != PublicationStatus.PUBLISHED.value:
        raise RecruitmentError("drive_save_requires_published_drive")

    drive_values = DriveUpdate.model_validate(drive.pending_changes).model_dump(exclude_unset=True)
    company_id = drive_values.get("company_id", drive.company_id)
    company = await db.scalar(
        select(Company).where(
            Company.id == company_id,
            Company.institution_id == institution,
            Company.status != PublicationStatus.ARCHIVED.value,
        )
    )
    if company is None:
        raise RecruitmentError("company_not_found")
    opens_at = drive_values.get("opens_at", drive.opens_at)
    deadline_at = drive_values.get("deadline_at", drive.deadline_at)
    if _utc(opens_at) >= _utc(deadline_at):
        raise RecruitmentError("drive_window_invalid")
    if _utc(deadline_at) <= datetime.now(UTC):
        raise RecruitmentError("drive_deadline_elapsed")

    roles = (
        await db.scalars(
            select(PlacementRole)
            .where(PlacementRole.drive_id == drive.id)
            .order_by(PlacementRole.created_at)
            .with_for_update()
        )
    ).all()
    if not roles:
        raise RecruitmentError("drive_requires_published_role")

    activated_role_ids: list[UUID] = []
    for role in roles:
        if role.pending_changes:
            role_values = RoleUpdate.model_validate(role.pending_changes).model_dump(
                exclude_unset=True
            )
            for key, value in role_values.items():
                setattr(role, key, value)
            role.pending_changes = {}

        draft_rule = await db.scalar(
            select(EligibilityRuleSet)
            .where(
                EligibilityRuleSet.role_id == role.id,
                EligibilityRuleSet.status == RuleSetStatus.DRAFT.value,
            )
            .order_by(EligibilityRuleSet.version.desc())
            .limit(1)
        )
        if draft_rule is not None:
            await publish_rule_set(
                db,
                institution,
                role.id,
                draft_rule.id,
                allow_published_drive=True,
            )

        published_rule = await db.scalar(
            select(EligibilityRuleSet.id).where(
                EligibilityRuleSet.role_id == role.id,
                EligibilityRuleSet.status == RuleSetStatus.PUBLISHED.value,
            )
        )
        if published_rule is None:
            raise RecruitmentError("role_requires_published_rules")
        if role.status == PublicationStatus.DRAFT.value:
            role.status = PublicationStatus.PUBLISHED.value
            role.published_at = datetime.now(UTC)
            activated_role_ids.append(role.id)
        elif role.status != PublicationStatus.PUBLISHED.value:
            raise RecruitmentError("role_save_transition_invalid")

    for key, value in drive_values.items():
        setattr(drive, key, value)
    drive.pending_changes = {}
    await db.flush()
    await db.refresh(drive)
    return drive, activated_role_ids


async def duplicate_drive(
    db: AsyncSession,
    institution_id: UUID | None,
    drive_id: UUID,
    actor_user_id: UUID,
) -> PlacementDrive:
    source = await _owned_drive(db, institution_id, drive_id)
    clone = PlacementDrive(
        institution_id=source.institution_id,
        company_id=source.company_id,
        title=f"{source.title} — copy",
        description=source.description,
        location=source.location,
        work_mode=source.work_mode,
        opens_at=source.opens_at,
        deadline_at=source.deadline_at,
        status=PublicationStatus.DRAFT.value,
    )
    db.add(clone)
    await db.flush()
    source_roles = (
        await db.scalars(select(PlacementRole).where(PlacementRole.drive_id == source.id))
    ).all()
    source_role_ids = [item.id for item in source_roles]
    rule_candidates = (
        (
            await db.scalars(
                select(EligibilityRuleSet)
                .where(EligibilityRuleSet.role_id.in_(source_role_ids))
                .order_by(EligibilityRuleSet.role_id, EligibilityRuleSet.version.desc())
            )
        ).all()
        if source_role_ids
        else []
    )
    latest_rules_by_role: dict[UUID, EligibilityRuleSet] = {}
    for rule_set in rule_candidates:
        latest_rules_by_role.setdefault(rule_set.role_id, rule_set)
    clones: list[PlacementRole | EligibilityRuleSet] = []
    for source_role in source_roles:
        role = PlacementRole(
            id=uuid4(),
            institution_id=source_role.institution_id,
            drive_id=clone.id,
            title=source_role.title,
            description=source_role.description,
            employment_type=source_role.employment_type,
            location=source_role.location,
            work_mode=source_role.work_mode,
            salary_display=source_role.salary_display,
            skills=list(source_role.skills),
            requirements=list(source_role.requirements),
            status=PublicationStatus.DRAFT.value,
        )
        clones.append(role)
        latest_rules = latest_rules_by_role.get(source_role.id)
        if latest_rules:
            clones.append(
                EligibilityRuleSet(
                    institution_id=source_role.institution_id,
                    role_id=role.id,
                    version=1,
                    status=RuleSetStatus.DRAFT.value,
                    rules=list(latest_rules.rules),
                    created_by_user_id=actor_user_id,
                )
            )
    # These mappers have no ORM relationship ordering. Persist role parents before
    # dependent rules so PostgreSQL's immediate FK checks also accept the copy.
    db.add_all(item for item in clones if isinstance(item, PlacementRole))
    await db.flush()
    db.add_all(item for item in clones if isinstance(item, EligibilityRuleSet))
    await db.flush()
    await db.refresh(clone)
    return clone


async def _owned_role(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID, *, lock: bool = False
) -> PlacementRole:
    query = select(PlacementRole).where(
        PlacementRole.id == role_id,
        PlacementRole.institution_id == _institution(institution_id),
    )
    role = await db.scalar(query.with_for_update() if lock else query)
    if role is None:
        raise RecruitmentError("role_not_found")
    return role


async def role_response(
    db: AsyncSession,
    role: PlacementRole,
    *,
    include_pending: bool = False,
    drive: PlacementDrive | None = None,
    company: Company | None = None,
) -> RoleResponse:
    if drive is None or company is None:
        drive, company = (
            await db.execute(
                select(PlacementDrive, Company)
                .join(Company, Company.id == PlacementDrive.company_id)
                .where(PlacementDrive.id == role.drive_id)
            )
        ).one()
    return RoleResponse(
        id=role.id,
        drive_id=role.drive_id,
        company_name=company.name,
        drive_title=drive.title,
        title=role.title,
        description=role.description,
        employment_type=role.employment_type,
        location=role.location,
        work_mode=role.work_mode,
        salary_display=role.salary_display,
        skills=list(role.skills),
        requirements=list(role.requirements),
        status=role.status,
        published_at=role.published_at,
        deadline_at=drive.deadline_at,
        pending_changes=dict(role.pending_changes) if include_pending else {},
    )


async def list_roles(
    db: AsyncSession, institution_id: UUID | None, drive_id: UUID
) -> list[RoleResponse]:
    await _owned_drive(db, institution_id, drive_id)
    roles = (
        await db.scalars(
            select(PlacementRole)
            .where(PlacementRole.drive_id == drive_id)
            .order_by(PlacementRole.created_at)
        )
    ).all()
    return [await role_response(db, item, include_pending=True) for item in roles]


async def create_role(
    db: AsyncSession,
    institution_id: UUID | None,
    drive_id: UUID,
    payload: RoleCreate,
) -> PlacementRole:
    drive = await _owned_drive(db, institution_id, drive_id)
    if drive.status not in {
        PublicationStatus.DRAFT.value,
        PublicationStatus.PUBLISHED.value,
    }:
        raise RecruitmentError("published_drive_is_immutable")
    role = PlacementRole(
        institution_id=_institution(institution_id), drive_id=drive.id, **payload.model_dump()
    )
    db.add(role)
    await db.flush()
    await db.refresh(role)
    return role


async def update_role(
    db: AsyncSession,
    institution_id: UUID | None,
    role_id: UUID,
    payload: RoleUpdate,
) -> PlacementRole:
    role = await _owned_role(db, institution_id, role_id, lock=True)
    drive = await _owned_drive(db, institution_id, role.drive_id)
    if drive.status not in {
        PublicationStatus.DRAFT.value,
        PublicationStatus.PUBLISHED.value,
    }:
        raise RecruitmentError("published_role_is_immutable")
    values = payload.model_dump(exclude_unset=True)
    if (
        role.status == PublicationStatus.PUBLISHED.value
        and drive.status == PublicationStatus.PUBLISHED.value
    ):
        pending = dict(role.pending_changes)
        pending.update(payload.model_dump(mode="json", exclude_unset=True))
        RoleUpdate.model_validate(pending)
        role.pending_changes = pending
    elif role.status in {
        PublicationStatus.DRAFT.value,
        PublicationStatus.PUBLISHED.value,
    }:
        for key, value in values.items():
            setattr(role, key, value)
    else:
        raise RecruitmentError("published_role_is_immutable")
    await db.flush()
    await db.refresh(role)
    return role


async def publish_role(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID
) -> PlacementRole:
    role = await _owned_role(db, institution_id, role_id, lock=True)
    if role.status != PublicationStatus.DRAFT.value:
        raise RecruitmentError("role_publish_transition_invalid")
    drive = await _owned_drive(db, institution_id, role.drive_id)
    if drive.status == PublicationStatus.PUBLISHED.value:
        raise RecruitmentError("drive_save_required")
    if _utc(drive.deadline_at) <= datetime.now(UTC):
        raise RecruitmentError("role_deadline_elapsed")
    rules = await db.scalar(
        select(EligibilityRuleSet.id).where(
            EligibilityRuleSet.role_id == role.id,
            EligibilityRuleSet.status == RuleSetStatus.PUBLISHED.value,
        )
    )
    if rules is None:
        raise RecruitmentError("role_requires_published_rules")
    role.status = PublicationStatus.PUBLISHED.value
    role.published_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(role)
    return role


async def preview_role_eligibility(
    db: AsyncSession,
    institution_id: UUID | None,
    role_id: UUID,
    facts: dict[str, object | None],
) -> EligibilityResponse:
    await _owned_role(db, institution_id, role_id)
    rule_set = await db.scalar(
        select(EligibilityRuleSet)
        .where(EligibilityRuleSet.role_id == role_id)
        .order_by(EligibilityRuleSet.version.desc())
    )
    return _eligibility(rule_set, facts)


def rule_set_response(rule_set: EligibilityRuleSet) -> RuleSetResponse:
    return RuleSetResponse(
        id=rule_set.id,
        role_id=rule_set.role_id,
        version=rule_set.version,
        status=rule_set.status,
        rules=list(rule_set.rules),
        policy_references=list(rule_set.policy_references),
        created_by_user_id=rule_set.created_by_user_id,
        published_at=rule_set.published_at,
        created_at=rule_set.created_at,
        updated_at=rule_set.updated_at,
    )


async def _approved_policy_references(
    db: AsyncSession, institution_id: UUID, policy_ids: list[UUID]
) -> list[dict[str, object]]:
    if not policy_ids:
        return []
    policies = (
        await db.scalars(
            select(PolicyDocument).where(
                PolicyDocument.institution_id == institution_id,
                PolicyDocument.id.in_(policy_ids),
                PolicyDocument.status == ReviewStatus.APPROVED.value,
            )
        )
    ).all()
    by_id = {item.id: item for item in policies}
    if any(policy_id not in by_id for policy_id in policy_ids):
        raise RecruitmentError("approved_policy_reference_not_found")
    return [
        {
            "id": str(policy.id),
            "title": policy.title,
            "version": policy.version,
            "source_reference": policy.source_reference,
            "approved_at": policy.approved_at.isoformat() if policy.approved_at else None,
        }
        for policy_id in policy_ids
        for policy in [by_id[policy_id]]
    ]


async def list_rule_sets(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID
) -> list[RuleSetResponse]:
    await _owned_role(db, institution_id, role_id)
    items = (
        await db.scalars(
            select(EligibilityRuleSet)
            .where(EligibilityRuleSet.role_id == role_id)
            .order_by(EligibilityRuleSet.version.desc())
        )
    ).all()
    return [rule_set_response(item) for item in items]


async def create_rule_set(
    db: AsyncSession,
    institution_id: UUID | None,
    role_id: UUID,
    actor_user_id: UUID,
    payload: RuleSetCreate,
) -> EligibilityRuleSet:
    institution = _institution(institution_id)
    await _owned_role(db, institution, role_id)
    policy_references = await _approved_policy_references(db, institution, payload.policy_ids)
    version = (
        await db.scalar(
            select(func.max(EligibilityRuleSet.version)).where(
                EligibilityRuleSet.role_id == role_id
            )
        )
        or 0
    ) + 1
    item = EligibilityRuleSet(
        institution_id=institution,
        role_id=role_id,
        version=version,
        rules=[rule.model_dump(mode="json") for rule in payload.rules],
        policy_references=policy_references,
        created_by_user_id=actor_user_id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


async def publish_rule_set(
    db: AsyncSession,
    institution_id: UUID | None,
    role_id: UUID,
    rule_set_id: UUID,
    *,
    allow_published_drive: bool = False,
) -> EligibilityRuleSet:
    role = await _owned_role(db, institution_id, role_id)
    drive = await _owned_drive(db, institution_id, role.drive_id)
    if drive.status == PublicationStatus.PUBLISHED.value and not allow_published_drive:
        raise RecruitmentError("drive_save_required")
    item = await db.scalar(
        select(EligibilityRuleSet)
        .where(
            EligibilityRuleSet.id == rule_set_id,
            EligibilityRuleSet.role_id == role_id,
            EligibilityRuleSet.institution_id == _institution(institution_id),
        )
        .with_for_update()
    )
    if item is None:
        raise RecruitmentError("rule_set_not_found")
    if item.status != RuleSetStatus.DRAFT.value:
        raise RecruitmentError("rule_set_publish_transition_invalid")
    RuleSetCreate(rules=[Rule.model_validate(rule) for rule in item.rules])
    policy_ids = [UUID(str(reference["id"])) for reference in item.policy_references]
    if policy_ids:
        current_references = await _approved_policy_references(
            db, _institution(institution_id), policy_ids
        )
        if current_references != list(item.policy_references):
            raise RecruitmentError("policy_reference_changed")
    previous = (
        await db.scalars(
            select(EligibilityRuleSet).where(
                EligibilityRuleSet.role_id == role_id,
                EligibilityRuleSet.status == RuleSetStatus.PUBLISHED.value,
            )
        )
    ).all()
    for published in previous:
        published.status = RuleSetStatus.RETIRED.value
    item.status = RuleSetStatus.PUBLISHED.value
    item.published_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(item)
    return item


async def _student_facts(
    db: AsyncSession, institution_id: UUID, student_user_id: UUID
) -> dict[str, object | None]:
    profile = await db.scalar(
        select(StudentProfile).where(
            StudentProfile.user_id == student_user_id,
            StudentProfile.institution_id == institution_id,
        )
    )
    education = profile.education[0] if profile and profile.education else {}
    links = profile.external_links if profile else {}
    resume_exists = await db.scalar(
        select(ResumeVersion.id).where(
            ResumeVersion.user_id == student_user_id,
            ResumeVersion.institution_id == institution_id,
            ResumeVersion.status == ResumeStatus.COMPLETED.value,
            ResumeVersion.scan_status == ScanStatus.CLEAN.value,
        )
    )
    score = education.get("score")
    scale = education.get("score_scale")
    return {
        "department": profile.department if profile else None,
        "degree": education.get("degree"),
        "branch": education.get("branch"),
        "graduation_year": education.get("graduation_year"),
        "cgpa": score if scale == "cgpa_10" else None,
        "active_backlogs": None,
        "github": links.get("github"),
        "portfolio": links.get("portfolio"),
        "resume": resume_exists is not None,
    }


def _eligibility(
    rule_set: EligibilityRuleSet | None, facts: dict[str, object | None]
) -> EligibilityResponse:
    if rule_set is None:
        return EligibilityResponse(
            status="unavailable",
            rule_set_id=None,
            rule_version=None,
            results=[],
            missing_evidence=[],
        )
    evaluated = evaluate(
        str(rule_set.version), [Rule.model_validate(item) for item in rule_set.rules], facts
    )
    results = list(evaluated["results"])
    missing = [str(item["label"]) for item in results if item["passed"] is None]
    return EligibilityResponse(
        status=evaluated["status"],
        rule_set_id=rule_set.id,
        rule_version=str(rule_set.version),
        results=results,
        missing_evidence=missing,
    )


async def _published_rules(
    db: AsyncSession, role_ids: list[UUID]
) -> dict[UUID, EligibilityRuleSet]:
    if not role_ids:
        return {}
    items = (
        await db.scalars(
            select(EligibilityRuleSet)
            .where(
                EligibilityRuleSet.role_id.in_(role_ids),
                EligibilityRuleSet.status == RuleSetStatus.PUBLISHED.value,
            )
            .order_by(EligibilityRuleSet.version.desc())
        )
    ).all()
    return {item.role_id: item for item in items}


async def list_opportunities(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    *,
    query: str | None,
    location: str | None,
    work_mode: str | None,
    skill: str | None,
    saved_only: bool,
    page: int,
    page_size: int,
    eligibility_status: str | None = None,
    application_status: str | None = None,
    deadline_within_days: int | None = None,
    sort: str = "deadline",
    unapplied_only: bool = False,
) -> OpportunityPage:
    institution = _institution(institution_id)
    now = datetime.now(UTC)
    statement = (
        select(PlacementRole, PlacementDrive, Company)
        .join(PlacementDrive, PlacementDrive.id == PlacementRole.drive_id)
        .join(Company, Company.id == PlacementDrive.company_id)
        .where(
            PlacementRole.institution_id == institution,
            PlacementRole.status == PublicationStatus.PUBLISHED.value,
            PlacementDrive.status == PublicationStatus.PUBLISHED.value,
            PlacementDrive.opens_at <= now,
            PlacementDrive.deadline_at >= now,
        )
    )
    if query:
        needle = f"%{query.strip()}%"
        statement = statement.where(
            or_(
                PlacementRole.title.ilike(needle),
                PlacementDrive.title.ilike(needle),
                Company.name.ilike(needle),
                PlacementRole.description.ilike(needle),
            )
        )
    if location:
        statement = statement.where(PlacementRole.location.ilike(f"%{location.strip()}%"))
    if work_mode:
        statement = statement.where(PlacementRole.work_mode == work_mode)
    if skill:
        statement = statement.where(_skill_filter(skill))
    if deadline_within_days is not None:
        statement = statement.where(
            PlacementDrive.deadline_at <= now + timedelta(days=deadline_within_days)
        )
    if saved_only:
        statement = statement.join(
            SavedOpportunity,
            (SavedOpportunity.role_id == PlacementRole.id)
            & (SavedOpportunity.student_user_id == student_user_id),
        )
    if unapplied_only:
        statement = statement.where(
            ~PlacementRole.id.in_(
                select(Application.role_id).where(
                    Application.student_user_id == student_user_id,
                    Application.institution_id == institution,
                )
            )
        )
    all_roles = (
        await db.execute(
            statement.order_by(
                PlacementDrive.deadline_at, PlacementRole.created_at, PlacementRole.id
            )
        )
    ).all()
    role_ids = [item[0].id for item in all_roles]
    rules = await _published_rules(db, role_ids)
    facts = await _student_facts(db, institution, student_user_id)
    saved_ids = set(
        (
            await db.scalars(
                select(SavedOpportunity.role_id).where(
                    SavedOpportunity.student_user_id == student_user_id,
                    SavedOpportunity.role_id.in_(role_ids),
                )
            )
        ).all()
    )
    applications = {
        item.role_id: item
        for item in (
            await db.scalars(
                select(Application).where(
                    Application.student_user_id == student_user_id,
                    Application.role_id.in_(role_ids),
                )
            )
        ).all()
    }
    candidates: list[OpportunityResponse] = []
    for role, drive, company in all_roles:
        base = await role_response(db, role, drive=drive, company=company)
        application = applications.get(role.id)
        candidates.append(
            OpportunityResponse(
                **base.model_dump(),
                eligibility=_eligibility(rules.get(role.id), facts),
                saved=role.id in saved_ids,
                application_id=application.id if application else None,
                application_status=application.status if application else None,
            )
        )
    filtered = [
        item
        for item in candidates
        if (eligibility_status is None or item.eligibility.status == eligibility_status)
        and (application_status is None or item.application_status == application_status)
    ]
    if sort == "newest":
        filtered.sort(
            key=lambda item: (item.published_at or datetime.min.replace(tzinfo=UTC), str(item.id)),
            reverse=True,
        )
    elif sort == "company":
        filtered.sort(
            key=lambda item: (item.company_name.casefold(), item.title.casefold(), str(item.id))
        )
    total = len(filtered)
    items = filtered[(page - 1) * page_size : page * page_size]
    filter_active = any(
        value
        for value in (
            query,
            location,
            work_mode,
            skill,
            saved_only,
            eligibility_status,
            application_status,
            deadline_within_days,
        )
    )
    profile_incomplete = not facts.get("degree") or not facts.get("graduation_year")
    empty_reason = None
    if not items:
        empty_reason = (
            "filters_exclude_results"
            if filter_active
            else "profile_incomplete"
            if all_roles and profile_incomplete
            else "no_published_drive"
        )
    return OpportunityPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        empty_reason=empty_reason,
    )


async def get_opportunity(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID, role_id: UUID
) -> OpportunityResponse:
    institution = _institution(institution_id)
    now = datetime.now(UTC)
    role = await db.scalar(
        select(PlacementRole)
        .join(PlacementDrive, PlacementDrive.id == PlacementRole.drive_id)
        .where(
            PlacementRole.id == role_id,
            PlacementRole.institution_id == institution,
            PlacementRole.status == PublicationStatus.PUBLISHED.value,
            PlacementDrive.status == PublicationStatus.PUBLISHED.value,
            PlacementDrive.opens_at <= now,
            PlacementDrive.deadline_at >= now,
        )
    )
    if role is None:
        raise RecruitmentError("opportunity_not_found")
    rule_set = (await _published_rules(db, [role.id])).get(role.id)
    facts = await _student_facts(db, institution, student_user_id)
    saved = await db.scalar(
        select(SavedOpportunity.id).where(
            SavedOpportunity.student_user_id == student_user_id,
            SavedOpportunity.role_id == role.id,
        )
    )
    application = await db.scalar(
        select(Application).where(
            Application.student_user_id == student_user_id,
            Application.role_id == role.id,
        )
    )
    base = await role_response(db, role)
    return OpportunityResponse(
        **base.model_dump(),
        eligibility=_eligibility(rule_set, facts),
        saved=saved is not None,
        application_id=application.id if application else None,
        application_status=application.status if application else None,
    )


async def toggle_saved(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID, role_id: UUID
) -> bool:
    await get_opportunity(db, institution_id, student_user_id, role_id)
    existing = await db.scalar(
        select(SavedOpportunity).where(
            SavedOpportunity.student_user_id == student_user_id,
            SavedOpportunity.role_id == role_id,
        )
    )
    if existing:
        await db.delete(existing)
        await db.flush()
        return False
    db.add(
        SavedOpportunity(
            institution_id=_institution(institution_id),
            student_user_id=student_user_id,
            role_id=role_id,
            created_at=datetime.now(UTC),
        )
    )
    await db.flush()
    return True


async def _application_response(db: AsyncSession, application: Application) -> ApplicationResponse:
    student = await db.get(User, application.student_user_id)
    institution = await db.get(Institution, application.institution_id)
    profile = await db.scalar(
        select(StudentProfile).where(StudentProfile.user_id == application.student_user_id)
    )
    history = (
        await db.scalars(
            select(ApplicationStatusEvent)
            .where(ApplicationStatusEvent.application_id == application.id)
            .order_by(ApplicationStatusEvent.created_at)
        )
    ).all()
    overrides = (
        await db.scalars(
            select(ApplicationOverride)
            .where(ApplicationOverride.application_id == application.id)
            .order_by(ApplicationOverride.created_at)
        )
    ).all()
    appeals = (
        await db.scalars(
            select(ApplicationAppeal)
            .where(ApplicationAppeal.application_id == application.id)
            .order_by(ApplicationAppeal.created_at)
        )
    ).all()
    from app.models.experience import CorrectionRequest
    from app.modules.recruitment.domain import TRANSITIONS

    request_counts = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(CorrectionRequest.status, func.count())
                .where(CorrectionRequest.application_id == application.id)
                .group_by(CorrectionRequest.status)
            )
        ).all()
    }
    open_requests = request_counts.get("open", 0)
    awaiting_review = request_counts.get("awaiting_review", 0)
    terminal = application.status in {"offered", "rejected", "withdrawn"}
    next_actor = "none" if terminal else "student" if open_requests else "placement_team"
    next_step = (
        "This application is closed. Its recorded history remains available."
        if terminal
        else "Respond to the placement team's information request."
        if open_requests
        else "Your response is with the placement team. No action is required from you."
        if awaiting_review
        else (
            f"Recorded stage: {application.status.replace('_', ' ')}. "
            "No student action is recorded."
        )
    )
    return ApplicationResponse(
        revision=application.revision,
        next_actor=next_actor,
        next_step=next_step,
        open_requests=open_requests,
        awaiting_review=awaiting_review,
        allowed_actions=sorted(
            str(s)
            for s in TRANSITIONS.get(ApplicationStatus(application.status), set())
            if str(s) != "withdrawn"
        ),
        id=application.id,
        role_id=application.role_id,
        student_user_id=application.student_user_id,
        student_name=(
            profile.full_name
            if profile and profile.full_name
            else student.email
            if student
            else "Student"
        ),
        student_email=student.email if student else "unavailable",
        resume_version_id=application.resume_version_id,
        status=application.status,
        role_snapshot=dict(application.role_snapshot),
        resume_snapshot=dict(application.resume_snapshot),
        facts_snapshot=dict(application.facts_snapshot),
        rule_snapshot=dict(application.rule_snapshot),
        eligibility_snapshot=dict(application.eligibility_snapshot),
        decision_snapshot=dict(application.decision_snapshot),
        profile_snapshot=dict(application.profile_snapshot),
        application_form_snapshot=dict(application.application_form_snapshot),
        disclosure_status=application.disclosure_status,
        institution_timezone=institution.timezone if institution else "UTC",
        created_at=application.created_at,
        updated_at=application.updated_at,
        withdrawn_at=application.withdrawn_at,
        withdrawal_reason=application.withdrawal_reason,
        can_withdraw=_can_withdraw(application),
        appeals=[
            ApplicationAppealResponse(
                id=item.id,
                kind=item.kind,
                status=item.status,
                reason=item.reason,
                supporting_evidence=list(item.supporting_evidence),
                administrator_response=item.administrator_response,
                created_at=item.created_at,
                updated_at=item.updated_at,
                resolved_at=item.resolved_at,
            )
            for item in appeals
        ],
        history=[
            StatusEventResponse(
                id=item.id,
                from_status=item.from_status,
                to_status=item.to_status,
                actor_user_id=item.actor_user_id,
                reason=item.reason,
                created_at=item.created_at,
            )
            for item in history
        ],
        overrides=[
            OverrideResponse(
                id=item.id,
                actor_user_id=item.actor_user_id,
                previous_status=item.previous_status,
                target_status=item.target_status,
                reason=item.reason,
                policy_reference=item.policy_reference,
                created_at=item.created_at,
            )
            for item in overrides
        ],
    )


async def create_application(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    idempotency_key: str,
    payload: ApplicationCreate,
) -> tuple[Application, bool]:
    institution = _institution(institution_id)
    await db.scalar(select(User.id).where(User.id == student_user_id).with_for_update())
    existing_key = await db.scalar(
        select(Application).where(
            Application.institution_id == institution,
            Application.student_user_id == student_user_id,
            Application.idempotency_key == idempotency_key,
        )
    )
    if existing_key:
        return existing_key, True
    duplicate = await db.scalar(
        select(Application.id).where(
            Application.student_user_id == student_user_id,
            Application.role_id == payload.role_id,
        )
    )
    if duplicate:
        raise RecruitmentError("application_already_exists")
    opportunity = await get_opportunity(db, institution, student_user_id, payload.role_id)
    if opportunity.eligibility.status not in {"eligible", "needs_manual_review"}:
        raise RecruitmentError("application_not_eligible")
    resume = await db.scalar(
        select(ResumeVersion).where(
            ResumeVersion.id == payload.resume_version_id,
            ResumeVersion.user_id == student_user_id,
            ResumeVersion.institution_id == institution,
            ResumeVersion.status == ResumeStatus.COMPLETED.value,
            ResumeVersion.scan_status == ScanStatus.CLEAN.value,
        )
    )
    if resume is None:
        raise RecruitmentError("resume_version_not_selectable")
    rule_set = await db.get(EligibilityRuleSet, opportunity.eligibility.rule_set_id)
    if rule_set is None:
        raise RecruitmentError("published_rule_set_not_found")
    facts = await _student_facts(db, institution, student_user_id)
    result = opportunity.eligibility.model_dump(mode="json")
    fingerprint = hashlib.sha256(
        json.dumps(
            {"facts": facts, "rules": rule_set.rules, "version": rule_set.version},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    evaluation = EligibilityEvaluation(
        institution_id=institution,
        role_id=payload.role_id,
        student_user_id=student_user_id,
        rule_set_id=rule_set.id,
        facts_snapshot=facts,
        result_snapshot=result,
        fingerprint=fingerprint,
        created_at=datetime.now(UTC),
    )
    db.add(evaluation)
    await db.flush()
    semantic_match = await db.scalar(
        select(SemanticMatchEvidence)
        .where(
            SemanticMatchEvidence.institution_id == institution,
            SemanticMatchEvidence.student_user_id == student_user_id,
            SemanticMatchEvidence.role_id == payload.role_id,
            SemanticMatchEvidence.resume_version_id == resume.id,
        )
        .order_by(SemanticMatchEvidence.created_at.desc())
    )
    semantic_reference: dict[str, object] | None = None
    if semantic_match is not None:
        semantic_reference = {
            "id": str(semantic_match.id),
            "status": semantic_match.status,
            "score": semantic_match.score,
            "profile_revision": semantic_match.profile_revision,
            "embedding_model": semantic_match.embedding_model,
            "embedding_version": semantic_match.embedding_version,
            "scoring_version": semantic_match.scoring_version,
        }
    application = Application(
        institution_id=institution,
        role_id=payload.role_id,
        student_user_id=student_user_id,
        resume_version_id=resume.id,
        eligibility_evaluation_id=evaluation.id,
        idempotency_key=idempotency_key,
        role_snapshot=opportunity.model_dump(mode="json", exclude={"eligibility", "saved"}),
        resume_snapshot={
            "id": str(resume.id),
            "version_number": resume.version_number,
            "checksum": resume.checksum,
            "original_name": resume.original_name,
        },
        facts_snapshot=facts,
        rule_snapshot={
            "id": str(rule_set.id),
            "version": rule_set.version,
            "rules": rule_set.rules,
            "policy_references": rule_set.policy_references,
        },
        eligibility_snapshot=result,
        decision_snapshot={
            "captured_at": datetime.now(UTC).isoformat(),
            "eligibility_evaluation_id": str(evaluation.id),
            "eligibility_fingerprint": fingerprint,
            "semantic_match": semantic_reference,
        },
    )
    db.add(application)
    await db.flush()
    db.add(
        ApplicationStatusEvent(
            application_id=application.id,
            from_status=None,
            to_status=ApplicationStatus.SUBMITTED.value,
            actor_user_id=student_user_id,
            reason="Application submitted by student",
            created_at=datetime.now(UTC),
        )
    )
    await db.flush()
    await db.refresh(application)
    return application, False


async def list_student_applications(
    db: AsyncSession, institution_id: UUID | None, student_user_id: UUID
) -> list[ApplicationResponse]:
    items = (
        await db.scalars(
            select(Application)
            .where(
                Application.institution_id == _institution(institution_id),
                Application.student_user_id == student_user_id,
            )
            .order_by(Application.created_at.desc())
        )
    ).all()
    return [await _application_response(db, item) for item in items]


def _application_deadline(application: Application) -> datetime | None:
    raw = application.role_snapshot.get("deadline_at")
    if not isinstance(raw, str):
        return None
    try:
        return _utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


def _can_withdraw(application: Application, now: datetime | None = None) -> bool:
    deadline = _application_deadline(application)
    current = now or datetime.now(UTC)
    return (
        application.status
        in {
            ApplicationStatus.SUBMITTED.value,
            ApplicationStatus.UNDER_REVIEW.value,
        }
        and deadline is not None
        and current <= deadline
    )


async def _owned_student_application(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    application_id: UUID,
) -> Application:
    item = await db.scalar(
        select(Application)
        .where(
            Application.id == application_id,
            Application.institution_id == _institution(institution_id),
            Application.student_user_id == student_user_id,
        )
        .with_for_update()
    )
    if item is None:
        raise RecruitmentError("application_not_found")
    return item


async def get_student_application(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    application_id: UUID,
) -> ApplicationResponse:
    application = await _owned_student_application(
        db, institution_id, student_user_id, application_id
    )
    return await _application_response(db, application)


async def withdraw_application(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    application_id: UUID,
    payload: ApplicationWithdrawal,
) -> tuple[Application, bool]:
    application = await _owned_student_application(
        db, institution_id, student_user_id, application_id
    )
    if application.status == ApplicationStatus.WITHDRAWN.value:
        return application, True
    if not _can_withdraw(application):
        deadline = _application_deadline(application)
        if deadline is not None and datetime.now(UTC) > deadline:
            raise RecruitmentError("application_withdrawal_deadline_passed")
        raise RecruitmentError("application_withdrawal_not_permitted")
    previous = application.status
    now = datetime.now(UTC)
    application.status = ApplicationStatus.WITHDRAWN.value
    application.revision += 1
    from app.modules.experience.service import close_requests

    await close_requests(db, application, student_user_id)
    application.withdrawn_at = now
    application.withdrawal_reason = payload.reason
    db.add(
        ApplicationStatusEvent(
            application_id=application.id,
            from_status=previous,
            to_status=ApplicationStatus.WITHDRAWN.value,
            actor_user_id=student_user_id,
            reason=payload.reason,
            created_at=now,
        )
    )
    await db.flush()
    await db.refresh(application)
    return application, False


async def create_application_appeal(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    application_id: UUID,
    idempotency_key: str,
    payload: ApplicationAppealCreate,
) -> tuple[ApplicationAppeal, bool]:
    application = await _owned_student_application(
        db, institution_id, student_user_id, application_id
    )
    existing = await db.scalar(
        select(ApplicationAppeal).where(
            ApplicationAppeal.application_id == application.id,
            ApplicationAppeal.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, True
    active = await db.scalar(
        select(ApplicationAppeal.id).where(
            ApplicationAppeal.application_id == application.id,
            ApplicationAppeal.status.in_({"submitted", "under_review"}),
        )
    )
    if active is not None:
        raise RecruitmentError("application_appeal_already_open")
    if application.status not in {
        ApplicationStatus.SUBMITTED.value,
        ApplicationStatus.UNDER_REVIEW.value,
        ApplicationStatus.REJECTED.value,
    }:
        raise RecruitmentError("application_appeal_not_permitted")
    appeal = ApplicationAppeal(
        institution_id=_institution(institution_id),
        application_id=application.id,
        student_user_id=student_user_id,
        idempotency_key=idempotency_key,
        kind=payload.kind,
        reason=payload.reason,
        supporting_evidence=payload.supporting_evidence,
    )
    db.add(appeal)
    await db.flush()
    await db.refresh(appeal)
    return appeal, False


def application_appeal_response(appeal: ApplicationAppeal) -> ApplicationAppealResponse:
    return ApplicationAppealResponse(
        id=appeal.id,
        kind=appeal.kind,
        status=appeal.status,
        reason=appeal.reason,
        supporting_evidence=list(appeal.supporting_evidence),
        administrator_response=appeal.administrator_response,
        created_at=appeal.created_at,
        updated_at=appeal.updated_at,
        resolved_at=appeal.resolved_at,
    )


async def resolve_application_appeal(
    db: AsyncSession,
    institution_id: UUID | None,
    actor_user_id: UUID,
    appeal_id: UUID,
    payload: ApplicationAppealResolution,
) -> ApplicationAppeal:
    appeal = await db.scalar(
        select(ApplicationAppeal)
        .where(
            ApplicationAppeal.id == appeal_id,
            ApplicationAppeal.institution_id == _institution(institution_id),
        )
        .with_for_update()
    )
    if appeal is None:
        raise RecruitmentError("application_appeal_not_found")
    if appeal.status in {"approved", "declined"}:
        raise RecruitmentError("application_appeal_already_resolved")
    appeal.status = payload.status
    appeal.administrator_response = payload.administrator_response
    appeal.resolved_by_user_id = actor_user_id
    appeal.resolved_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(appeal)
    return appeal


async def get_application_deadline_calendar(
    db: AsyncSession,
    institution_id: UUID | None,
    student_user_id: UUID,
    application_id: UUID,
) -> str:
    application = await _owned_student_application(
        db, institution_id, student_user_id, application_id
    )
    return application_deadline_calendar(application)


def application_deadline_calendar(application: Application) -> str:
    deadline = _application_deadline(application)
    if deadline is None:
        raise RecruitmentError("application_deadline_unavailable")

    def escape(value: object) -> str:
        return (
            str(value)
            .replace("\\", "\\\\")
            .replace("\r", " ")
            .replace("\n", " ")
            .replace(",", "\\,")
            .replace(";", "\\;")
        )

    title = escape(application.role_snapshot.get("title", "Placement application deadline"))
    company = escape(application.role_snapshot.get("company_name", "CampusHire"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    deadline_value = deadline.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//CampusHire//Application Deadline//EN",
            "CALSCALE:GREGORIAN",
            "BEGIN:VEVENT",
            f"UID:application-{application.id}@campushire",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{deadline_value}",
            f"DTEND:{deadline_value}",
            f"SUMMARY:{title} application deadline",
            f"DESCRIPTION:{company} · CampusHire application {application.id}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


async def list_admin_applications(
    db: AsyncSession,
    institution_id: UUID | None,
    role_id: UUID | None,
    status: str | None,
    *,
    page: int,
    page_size: int,
) -> AdminApplicationPage:
    statement = select(Application).where(
        Application.institution_id == _institution(institution_id)
    )
    if role_id:
        statement = statement.where(Application.role_id == role_id)
    if status:
        statement = statement.where(Application.status == status)
    total = (
        await db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    )
    items = (
        await db.scalars(
            statement.order_by(Application.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return AdminApplicationPage(
        items=[await _application_response(db, item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


async def _owned_application(
    db: AsyncSession, institution_id: UUID | None, application_id: UUID
) -> Application:
    item = await db.scalar(
        select(Application)
        .where(
            Application.id == application_id,
            Application.institution_id == _institution(institution_id),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise RecruitmentError("application_not_found")
    return item


async def update_application_status(
    db: AsyncSession,
    institution_id: UUID | None,
    application_id: UUID,
    actor_user_id: UUID,
    payload: ApplicationStatusUpdate,
) -> Application:
    application = await _owned_application(db, institution_id, application_id)
    if payload.expected_revision is not None and application.revision != payload.expected_revision:
        raise RecruitmentError("revision_conflict")
    try:
        validate_transition(
            ApplicationStatus(application.status), ApplicationStatus(payload.status)
        )
    except (ValueError, KeyError) as error:
        raise RecruitmentError("application_status_transition_invalid") from error
    previous = application.status
    application.status = payload.status
    application.revision += 1
    from app.modules.experience.service import close_requests

    await close_requests(db, application, actor_user_id)
    db.add(
        ApplicationStatusEvent(
            application_id=application.id,
            from_status=previous,
            to_status=payload.status,
            actor_user_id=actor_user_id,
            reason=payload.reason,
            created_at=datetime.now(UTC),
        )
    )
    await db.flush()
    await db.refresh(application)
    return application


async def preview_bulk_application_status(
    db: AsyncSession,
    institution_id: UUID | None,
    payload: BulkApplicationStatusRequest,
) -> BulkApplicationPreviewResponse:
    institution = _institution(institution_id)
    applications = (
        await db.scalars(
            select(Application).where(
                Application.institution_id == institution,
                Application.id.in_(payload.application_ids),
            )
        )
    ).all()
    by_id = {item.id: item for item in applications}
    if len(by_id) != len(payload.application_ids):
        raise RecruitmentError("bulk_application_not_found")
    items: list[BulkApplicationPreviewItem] = []
    for application_id in payload.application_ids:
        application = by_id[application_id]
        try:
            validate_transition(
                ApplicationStatus(application.status),
                ApplicationStatus(payload.status),
            )
            allowed = True
            explanation = "Transition follows the documented application lifecycle."
        except ValueError as error:
            allowed = False
            explanation = str(error)
        items.append(
            BulkApplicationPreviewItem(
                revision=application.revision,
                application_id=application.id,
                current_status=application.status,
                target_status=payload.status,
                allowed=allowed,
                explanation=explanation,
            )
        )
    return BulkApplicationPreviewResponse(
        items=items,
        allowed_count=sum(item.allowed for item in items),
        blocked_count=sum(not item.allowed for item in items),
    )


async def apply_bulk_application_status(
    db: AsyncSession,
    institution_id: UUID | None,
    actor_user_id: UUID,
    payload: BulkApplicationStatusRequest,
) -> list[Application]:
    preview = await preview_bulk_application_status(db, institution_id, payload)
    if preview.blocked_count:
        raise RecruitmentError("bulk_application_transition_invalid")
    updated: list[Application] = []
    if payload.expected_revisions is not None and set(payload.expected_revisions) != set(
        payload.application_ids
    ):
        raise RecruitmentError("revision_conflict")
    for application_id in sorted(payload.application_ids):
        status_payload = ApplicationStatusUpdate(
            status=payload.status,
            reason=payload.reason,
            expected_revision=payload.expected_revisions.get(application_id)
            if payload.expected_revisions
            else None,
        )
        updated.append(
            await update_application_status(
                db,
                institution_id,
                application_id,
                actor_user_id,
                status_payload,
            )
        )
    return updated


async def override_application(
    db: AsyncSession,
    institution_id: UUID | None,
    application_id: UUID,
    actor_user_id: UUID,
    payload: ApplicationOverrideCreate,
) -> Application:
    application = await _owned_application(db, institution_id, application_id)
    if payload.expected_revision is not None and application.revision != payload.expected_revision:
        raise RecruitmentError("revision_conflict")
    previous = application.status
    application.status = payload.status
    application.revision += 1
    from app.modules.experience.service import close_requests

    await close_requests(db, application, actor_user_id)
    now = datetime.now(UTC)
    db.add(
        ApplicationOverride(
            application_id=application.id,
            actor_user_id=actor_user_id,
            previous_status=previous,
            target_status=payload.status,
            reason=payload.reason,
            policy_reference=payload.policy_reference,
            created_at=now,
        )
    )
    db.add(
        ApplicationStatusEvent(
            application_id=application.id,
            from_status=previous,
            to_status=payload.status,
            actor_user_id=actor_user_id,
            reason=f"Override: {payload.reason}",
            created_at=now,
        )
    )
    await db.flush()
    await db.refresh(application)
    return application


async def response_for_application(
    db: AsyncSession, application: Application
) -> ApplicationResponse:
    return await _application_response(db, application)


async def delete_saved_for_closed_roles(db: AsyncSession, role_ids: list[UUID]) -> None:
    if role_ids:
        await db.execute(delete(SavedOpportunity).where(SavedOpportunity.role_id.in_(role_ids)))
