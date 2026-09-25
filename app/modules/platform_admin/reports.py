"""Read-only, cross-institution placement reports for the Platform Admin."""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.auth import Institution, User
from app.models.profile import StudentProfile
from app.models.recruitment import Application, Company, PlacementDrive, PlacementRole
from app.modules.platform_admin.schemas import (
    PlatformApplicationEvidence,
    PlatformDriveApplicant,
    PlatformDriveApplicantPage,
    PlatformDriveGroup,
    PlatformDriveGroupPage,
    PlatformDriveInstance,
    PlatformDriveInstitutionBreakdown,
)


def _drive_key(company: str, title: str, year: int) -> tuple[str, str, int]:
    return company.strip().casefold(), title.strip().casefold(), year


async def _drive_rows(
    db: AsyncSession, *, active_only: bool
) -> list[tuple[PlacementDrive, str, str]]:
    statement = (
        select(PlacementDrive, Company.name, Institution.name)
        .join(
            Company,
            and_(
                Company.id == PlacementDrive.company_id,
                Company.institution_id == PlacementDrive.institution_id,
            ),
        )
        .join(Institution, Institution.id == PlacementDrive.institution_id)
    )
    if active_only:
        now = datetime.now(UTC)
        statement = statement.where(
            PlacementDrive.status == "published",
            PlacementDrive.opens_at <= now,
            PlacementDrive.deadline_at >= now,
        )
    return [
        row._tuple()
        for row in (await db.execute(statement.order_by(PlacementDrive.opens_at.desc()))).all()
    ]


async def list_drive_groups(
    db: AsyncSession,
    *,
    active_only: bool,
    institution_id: UUID | None,
    query: str | None,
    page: int,
    page_size: int,
) -> PlatformDriveGroupPage:
    rows = await _drive_rows(db, active_only=active_only)
    groups: dict[tuple[str, str, int], list[tuple[PlacementDrive, str, str]]] = defaultdict(list)
    needle = (query or "").strip().casefold()
    for drive, company, institution in rows:
        if institution_id is not None and drive.institution_id != institution_id:
            continue
        if needle and needle not in company.casefold() and needle not in drive.title.casefold():
            continue
        groups[_drive_key(company, drive.title, drive.opens_at.year)].append(
            (drive, company, institution)
        )
    keys = sorted(groups, key=lambda key: (-key[2], key[0], key[1]))
    selected = keys[(page - 1) * page_size : page * page_size]
    drive_ids = [drive.id for key in selected for drive, _, _ in groups[key]]
    counts: dict[UUID, tuple[int, set[UUID]]] = {}
    if drive_ids:
        application_rows = (
            await db.execute(
                select(
                    PlacementRole.drive_id, Application.student_user_id, func.count(Application.id)
                )
                .join(
                    Application,
                    and_(
                        Application.role_id == PlacementRole.id,
                        Application.institution_id == PlacementRole.institution_id,
                    ),
                )
                .where(PlacementRole.drive_id.in_(drive_ids))
                .group_by(PlacementRole.drive_id, Application.student_user_id)
            )
        ).all()
        for drive_id, student_id, application_count in application_rows:
            count, students = counts.setdefault(drive_id, (0, set()))
            counts[drive_id] = (count + application_count, students | {student_id})
    items = []
    for key in selected:
        group_rows = groups[key]
        institutions: dict[UUID, PlatformDriveInstitutionBreakdown] = {}
        group_students: set[UUID] = set()
        for drive, _company, institution_name in group_rows:
            entry = institutions.get(drive.institution_id)
            if entry is None:
                entry = PlatformDriveInstitutionBreakdown(
                    institution_id=drive.institution_id,
                    institution_name=institution_name,
                    drive_ids=[],
                    drives=[],
                    application_count=0,
                    student_count=0,
                )
                institutions[drive.institution_id] = entry
            entry.drive_ids.append(drive.id)
            entry.drives.append(
                PlatformDriveInstance(
                    id=drive.id,
                    opens_at=drive.opens_at,
                    deadline_at=drive.deadline_at,
                    status=drive.status,
                )
            )
            count, students = counts.get(drive.id, (0, set()))
            entry.application_count += count
            group_students.update(students)
        # Count unique students across multiple roles/drives within each institution.
        for entry in institutions.values():
            entry.student_count = len(
                set().union(*(counts.get(drive_id, (0, set()))[1] for drive_id in entry.drive_ids))
            )
        items.append(
            PlatformDriveGroup(
                company_name=group_rows[0][1],
                drive_title=group_rows[0][0].title,
                cycle_year=key[2],
                drive_count=len(group_rows),
                application_count=sum(item.application_count for item in institutions.values()),
                student_count=len(group_students),
                institutions=sorted(institutions.values(), key=lambda item: item.institution_name),
            )
        )
    return PlatformDriveGroupPage(
        items=items, page=page, page_size=page_size, total=len(keys), generated_at=datetime.now(UTC)
    )


async def _matching_drive_ids(
    db: AsyncSession,
    *,
    company_name: str,
    drive_title: str,
    cycle_year: int,
    institution_id: UUID | None,
    drive_id: UUID | None,
) -> list[UUID]:
    key = _drive_key(company_name, drive_title, cycle_year)
    statement = (
        select(PlacementDrive.id)
        .join(
            Company,
            and_(
                Company.id == PlacementDrive.company_id,
                Company.institution_id == PlacementDrive.institution_id,
            ),
        )
        .where(
            func.lower(func.trim(Company.name)) == key[0],
            func.lower(func.trim(PlacementDrive.title)) == key[1],
            func.extract("year", PlacementDrive.opens_at) == cycle_year,
        )
    )
    if institution_id is not None:
        statement = statement.where(PlacementDrive.institution_id == institution_id)
    if drive_id is not None:
        statement = statement.where(PlacementDrive.id == drive_id)
    return list((await db.scalars(statement)).all())


def _applicant(
    row: tuple[
        Application, PlacementRole, PlacementDrive, Institution, StudentProfile | None, User
    ],
) -> PlatformDriveApplicant:
    application, role, drive, institution, profile, user = row
    snapshot_name = application.profile_snapshot.get("full_name")
    return PlatformDriveApplicant(
        application_id=application.id,
        drive_id=drive.id,
        institution_id=institution.id,
        institution_name=institution.name,
        student_user_id=user.id,
        student_name=str(snapshot_name or (profile.full_name if profile else None) or user.email),
        prn=profile.prn if profile and profile.institution_id == institution.id else None,
        prn_verified=bool(
            profile and profile.institution_id == institution.id and profile.prn_verified_at
        ),
        role_title=role.title,
        application_status=application.status,
        submitted_at=application.created_at,
    )


def _applicant_statement(drive_ids: list[UUID] | None = None) -> Select[Any]:
    statement = (
        select(Application, PlacementRole, PlacementDrive, Institution, StudentProfile, User)
        .join(
            PlacementRole,
            and_(
                PlacementRole.id == Application.role_id,
                PlacementRole.institution_id == Application.institution_id,
            ),
        )
        .join(
            PlacementDrive,
            and_(
                PlacementDrive.id == PlacementRole.drive_id,
                PlacementDrive.institution_id == Application.institution_id,
            ),
        )
        .join(Institution, Institution.id == Application.institution_id)
        .join(User, User.id == Application.student_user_id)
        .outerjoin(StudentProfile, StudentProfile.user_id == Application.student_user_id)
    )
    return statement.where(PlacementDrive.id.in_(drive_ids)) if drive_ids is not None else statement


async def list_drive_applicants(
    db: AsyncSession,
    *,
    company_name: str,
    drive_title: str,
    cycle_year: int,
    institution_id: UUID | None,
    drive_id: UUID | None,
    page: int,
    page_size: int,
) -> PlatformDriveApplicantPage:
    drive_ids = await _matching_drive_ids(
        db,
        company_name=company_name,
        drive_title=drive_title,
        cycle_year=cycle_year,
        institution_id=institution_id,
        drive_id=drive_id,
    )
    if not drive_ids:
        return PlatformDriveApplicantPage(items=[], page=page, page_size=page_size, total=0)
    statement = _applicant_statement(drive_ids)
    total = await db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = (
        await db.execute(
            statement.order_by(Application.created_at.desc(), Application.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PlatformDriveApplicantPage(
        items=[_applicant(cast(Any, row._tuple())) for row in rows],
        page=page,
        page_size=page_size,
        total=total,
    )


async def get_application_evidence(
    db: AsyncSession,
    application_id: UUID,
) -> PlatformApplicationEvidence | None:
    row = (await db.execute(_applicant_statement().where(Application.id == application_id))).first()
    if row is None:
        return None
    application = row[0]
    return PlatformApplicationEvidence(
        applicant=_applicant(cast(Any, row._tuple())),
        profile_snapshot=application.profile_snapshot or {},
        resume_snapshot=application.resume_snapshot or {},
        facts_snapshot=application.facts_snapshot or {},
        eligibility_snapshot=application.eligibility_snapshot or {},
        application_form_snapshot=application.application_form_snapshot or {},
        acknowledgment_snapshot=application.acknowledgment_snapshot or {},
        disclosure_status=application.disclosure_status,
        evidence_provenance=application.evidence_provenance,
    )
