import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User
from app.models.profile import StudentProfile
from app.models.recruitment import (
    Application,
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
    ApplicationCreate,
    ApplicationOverrideCreate,
    ApplicationResponse,
    ApplicationStatusUpdate,
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
    role_count = await db.scalar(
        select(func.count()).select_from(PlacementRole).where(PlacementRole.drive_id == drive.id)
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
        role_count=role_count or 0,
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
    drive = await _owned_drive(db, institution_id, drive_id, lock=True)
    if drive.status != PublicationStatus.DRAFT.value:
        raise RecruitmentError("published_drive_is_immutable")
    values = payload.model_dump(exclude_unset=True)
    opens_at = values.get("opens_at", drive.opens_at)
    deadline_at = values.get("deadline_at", drive.deadline_at)
    if _utc(opens_at) >= _utc(deadline_at):
        raise RecruitmentError("drive_window_invalid")
    for key, value in values.items():
        setattr(drive, key, value)
    await db.flush()
    await db.refresh(drive)
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


async def role_response(db: AsyncSession, role: PlacementRole) -> RoleResponse:
    row = (
        await db.execute(
            select(PlacementDrive, Company)
            .join(Company, Company.id == PlacementDrive.company_id)
            .where(PlacementDrive.id == role.drive_id)
        )
    ).one()
    drive, company = row
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
    return [await role_response(db, item) for item in roles]


async def create_role(
    db: AsyncSession,
    institution_id: UUID | None,
    drive_id: UUID,
    payload: RoleCreate,
) -> PlacementRole:
    drive = await _owned_drive(db, institution_id, drive_id)
    if drive.status != PublicationStatus.DRAFT.value:
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
    if role.status != PublicationStatus.DRAFT.value:
        raise RecruitmentError("published_role_is_immutable")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(role, key, value)
    await db.flush()
    await db.refresh(role)
    return role


async def publish_role(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID
) -> PlacementRole:
    role = await _owned_role(db, institution_id, role_id, lock=True)
    if role.status != PublicationStatus.DRAFT.value:
        raise RecruitmentError("role_publish_transition_invalid")
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


def rule_set_response(rule_set: EligibilityRuleSet) -> RuleSetResponse:
    return RuleSetResponse(
        id=rule_set.id,
        role_id=rule_set.role_id,
        version=rule_set.version,
        status=rule_set.status,
        rules=list(rule_set.rules),
        created_by_user_id=rule_set.created_by_user_id,
        published_at=rule_set.published_at,
        created_at=rule_set.created_at,
        updated_at=rule_set.updated_at,
    )


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
    await _owned_role(db, institution_id, role_id)
    version = (
        await db.scalar(
            select(func.max(EligibilityRuleSet.version)).where(
                EligibilityRuleSet.role_id == role_id
            )
        )
        or 0
    ) + 1
    item = EligibilityRuleSet(
        institution_id=_institution(institution_id),
        role_id=role_id,
        version=version,
        rules=[rule.model_dump(mode="json") for rule in payload.rules],
        created_by_user_id=actor_user_id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


async def publish_rule_set(
    db: AsyncSession, institution_id: UUID | None, role_id: UUID, rule_set_id: UUID
) -> EligibilityRuleSet:
    await _owned_role(db, institution_id, role_id)
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
) -> OpportunityPage:
    institution = _institution(institution_id)
    now = datetime.now(UTC)
    statement = (
        select(PlacementRole)
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
                Company.name.ilike(needle),
                PlacementRole.description.ilike(needle),
            )
        )
    if location:
        statement = statement.where(PlacementRole.location.ilike(f"%{location.strip()}%"))
    if work_mode:
        statement = statement.where(PlacementRole.work_mode == work_mode)
    if skill:
        statement = statement.where(PlacementRole.skills.contains([skill]))
    if saved_only:
        statement = statement.join(
            SavedOpportunity,
            (SavedOpportunity.role_id == PlacementRole.id)
            & (SavedOpportunity.student_user_id == student_user_id),
        )
    all_roles = (await db.scalars(statement.order_by(PlacementDrive.deadline_at))).all()
    total = len(all_roles)
    roles = all_roles[(page - 1) * page_size : page * page_size]
    role_ids = [item.id for item in roles]
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
    items: list[OpportunityResponse] = []
    for role in roles:
        base = await role_response(db, role)
        application = applications.get(role.id)
        items.append(
            OpportunityResponse(
                **base.model_dump(),
                eligibility=_eligibility(rules.get(role.id), facts),
                saved=role.id in saved_ids,
                application_id=application.id if application else None,
                application_status=application.status if application else None,
            )
        )
    return OpportunityPage(items=items, page=page, page_size=page_size, total=total)


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
    return ApplicationResponse(
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
        created_at=application.created_at,
        updated_at=application.updated_at,
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
        },
        eligibility_snapshot=result,
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
    total = await db.scalar(
        select(func.count()).select_from(statement.order_by(None).subquery())
    ) or 0
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
    try:
        validate_transition(
            ApplicationStatus(application.status), ApplicationStatus(payload.status)
        )
    except (ValueError, KeyError) as error:
        raise RecruitmentError("application_status_transition_invalid") from error
    previous = application.status
    application.status = payload.status
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


async def override_application(
    db: AsyncSession,
    institution_id: UUID | None,
    application_id: UUID,
    actor_user_id: UUID,
    payload: ApplicationOverrideCreate,
) -> Application:
    application = await _owned_application(db, institution_id, application_id)
    previous = application.status
    application.status = payload.status
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
