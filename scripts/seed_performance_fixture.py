from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.database import SessionFactory
from app.models.auth import (
    Institution,
    InstitutionMembership,
    MembershipStatus,
    User,
    UserRole,
)
from app.models.profile import StudentProfile
from app.models.recruitment import (
    Company,
    EligibilityRuleSet,
    PlacementDrive,
    PlacementRole,
)
from app.models.resume import ResumeStatus, ResumeVersion, ScanStatus
from app.modules.auth.security import hash_password


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} before seeding the synthetic performance fixture.")
    return value


def assert_safe_environment() -> None:
    if os.getenv("APP_ENV", "development") == "production":
        raise RuntimeError("The synthetic performance fixture cannot run in production.")
    if os.getenv("PERFORMANCE_FIXTURE_ACK") != "synthetic-only":
        raise RuntimeError("Set PERFORMANCE_FIXTURE_ACK=synthetic-only to confirm the data class.")


async def seed() -> dict[str, str]:
    assert_safe_environment()
    now = datetime.now(UTC)
    student_email = "student+performance@example.com"
    admin_email = "admin+performance@example.com"
    async with SessionFactory() as db:
        existing = await db.scalar(
            select(Institution).where(Institution.code == "performance-fixture")
        )
        if existing is not None:
            student = await db.scalar(select(User).where(User.email == student_email))
            admin = await db.scalar(select(User).where(User.email == admin_email))
            role = await db.scalar(
                select(PlacementRole).where(PlacementRole.institution_id == existing.id)
            )
            resume = await db.scalar(
                select(ResumeVersion)
                .where(ResumeVersion.institution_id == existing.id)
                .order_by(ResumeVersion.version_number)
            )
            if student is None or admin is None or role is None or resume is None:
                raise RuntimeError(
                    "The existing performance fixture is incomplete; use a clean database."
                )
            student.password_hash = hash_password(required("PERFORMANCE_STUDENT_PASSWORD"))
            admin.password_hash = hash_password(required("PERFORMANCE_ADMIN_PASSWORD"))
            await db.commit()
            return {
                "data_class": "synthetic-only",
                "student_email": student.email,
                "admin_email": admin.email,
                "institution_id": str(existing.id),
                "role_id": str(role.id),
                "resume_version_id": str(resume.id),
            }

        institution = Institution(code="performance-fixture", name="Performance Fixture Campus")
        admin = User(
            email=admin_email,
            password_hash=hash_password(required("PERFORMANCE_ADMIN_PASSWORD")),
            role=UserRole.TNP_ADMIN.value,
        )
        student = User(
            email=student_email,
            password_hash=hash_password(required("PERFORMANCE_STUDENT_PASSWORD")),
            role=UserRole.STUDENT.value,
        )
        db.add_all([institution, admin, student])
        await db.flush()
        db.add_all(
            [
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=admin.id,
                    role=UserRole.TNP_ADMIN.value,
                    status=MembershipStatus.ACTIVE.value,
                    verified_at=now,
                    verified_by_user_id=admin.id,
                ),
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=student.id,
                    role=UserRole.STUDENT.value,
                    status=MembershipStatus.ACTIVE.value,
                    verified_at=now,
                    verified_by_user_id=admin.id,
                ),
                StudentProfile(
                    user_id=student.id,
                    institution_id=institution.id,
                    full_name="Synthetic Performance Student",
                    institution_name=institution.name,
                    department="Computer Science",
                    academic_year="2026",
                    education=[
                        {
                            "program": "B.Tech CSE",
                            "institution": institution.name,
                            "score": 8.4,
                            "graduation_year": 2026,
                            "active_backlogs": 0,
                        }
                    ],
                    skills=[{"name": "Python"}, {"name": "SQL"}],
                    target_roles=["Software Engineer"],
                    onboarding_step=4,
                    readiness=100,
                    is_complete=True,
                ),
            ]
        )
        resume = ResumeVersion(
            user_id=student.id,
            institution_id=institution.id,
            version_number=1,
            storage_key="clean/performance-fixture/baseline.pdf",
            original_name="baseline.pdf",
            checksum="c" * 64,
            size_bytes=1_024,
            status=ResumeStatus.COMPLETED.value,
            scan_status=ScanStatus.CLEAN.value,
            scan_engine="synthetic-performance",
            scanned_at=now,
            page_count=1,
            extracted_text="Synthetic performance fixture with Python and SQL evidence.",
            extracted_data={"skills": ["Python", "SQL"], "projects": ["Placement platform"]},
            review_completed_at=now,
        )
        company = Company(institution_id=institution.id, name="Performance Example Labs")
        db.add_all([resume, company])
        await db.flush()
        drive = PlacementDrive(
            institution_id=institution.id,
            company_id=company.id,
            title="Synthetic Performance Drive",
            description="Synthetic load-measurement fixture",
            location="Remote",
            work_mode="remote",
            opens_at=now - timedelta(days=1),
            deadline_at=now + timedelta(days=7),
            status="published",
            published_at=now,
        )
        db.add(drive)
        await db.flush()
        role = PlacementRole(
            institution_id=institution.id,
            drive_id=drive.id,
            title="Synthetic Performance Engineer",
            description="Synthetic role for repeatable performance measurement",
            employment_type="full-time",
            location="Remote",
            work_mode="remote",
            skills=["Python", "SQL"],
            requirements=["CGPA >= 7.0"],
            status="published",
            published_at=now,
        )
        db.add(role)
        await db.flush()
        db.add(
            EligibilityRuleSet(
                institution_id=institution.id,
                role_id=role.id,
                version=1,
                status="published",
                rules=[
                    {
                        "field": "cgpa",
                        "operator": "gte",
                        "value": 7.0,
                        "label": "Minimum CGPA of 7.0",
                    }
                ],
                created_by_user_id=admin.id,
                published_at=now,
            )
        )
        await db.commit()
        return {
            "data_class": "synthetic-only",
            "student_email": student.email,
            "admin_email": admin.email,
            "institution_id": str(institution.id),
            "role_id": str(role.id),
            "resume_version_id": str(resume.id),
        }


def main() -> None:
    print(json.dumps(asyncio.run(seed()), sort_keys=True))


if __name__ == "__main__":
    main()
