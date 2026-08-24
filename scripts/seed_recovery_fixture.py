from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta

from app.core.database import SessionFactory
from app.models.auth import (
    AuditEvent,
    Institution,
    InstitutionMembership,
    MembershipStatus,
    User,
    UserRole,
)
from app.models.profile import StudentProfile
from app.models.recruitment import (
    Application,
    Company,
    EligibilityEvaluation,
    EligibilityRuleSet,
    PlacementDrive,
    PlacementRole,
)
from app.models.resume import (
    JobStatus,
    ResumeProcessingJob,
    ResumeStatus,
    ResumeVersion,
    ScanStatus,
)
from app.modules.auth.security import hash_password


async def seed() -> dict[str, object]:
    now = datetime.now(UTC)
    facts = {"program": "B.Tech CSE", "cgpa": 8.4, "active_backlogs": 0}
    rules = [
        {
            "field": "cgpa",
            "operator": "gte",
            "value": 7.0,
            "label": "Minimum CGPA of 7.0",
        }
    ]
    eligibility = {"status": "eligible", "requirements": [{"passed": True}]}
    role_snapshot = {"title": "Synthetic Recovery Engineer", "company": "Example Labs"}
    resume_snapshot = {
        "version_number": 1,
        "checksum": "a" * 64,
        "original_name": "synthetic-recovery.pdf",
    }
    rule_snapshot = {"version": 1, "rules": rules}
    snapshots = [role_snapshot, resume_snapshot, facts, rule_snapshot, eligibility]
    snapshot_hash = hashlib.sha256(
        json.dumps(snapshots, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    async with SessionFactory() as db:
        institution = Institution(code="recovery-fixture", name="Recovery Fixture Campus")
        admin = User(
            email="recovery-admin@example.com",
            password_hash=hash_password("synthetic recovery administrator"),
            role=UserRole.TNP_ADMIN.value,
        )
        student = User(
            email="recovery-student@example.com",
            password_hash=hash_password("synthetic recovery student"),
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
                    full_name="Synthetic Recovery Student",
                    institution_name=institution.name,
                    department="Computer Science",
                    academic_year="2026",
                    education=[{"program": "B.Tech CSE", "cgpa": 8.4}],
                    skills=[{"name": "Python"}],
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
            storage_key="clean/recovery-fixture/synthetic-recovery.pdf",
            original_name="synthetic-recovery.pdf",
            checksum="a" * 64,
            size_bytes=1_024,
            status=ResumeStatus.COMPLETED.value,
            scan_status=ScanStatus.CLEAN.value,
            scan_engine="synthetic-recovery",
            scanned_at=now,
            page_count=1,
            extracted_text="Synthetic recovery fixture",
            extracted_data={"skills": ["Python"], "projects": ["Recovery fixture"]},
            review_completed_at=now,
        )
        company = Company(institution_id=institution.id, name="Example Labs")
        db.add_all([resume, company])
        await db.flush()
        db.add(
            ResumeProcessingJob(
                resume_version_id=resume.id,
                status=JobStatus.QUEUED.value,
                available_at=now - timedelta(minutes=5),
            )
        )
        drive = PlacementDrive(
            institution_id=institution.id,
            company_id=company.id,
            title="Synthetic Recovery Drive",
            description="Synthetic recovery-only drive",
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
            title="Synthetic Recovery Engineer",
            description="Synthetic recovery-only role",
            employment_type="full-time",
            location="Remote",
            work_mode="remote",
            skills=["Python"],
            requirements=["CGPA >= 7.0"],
            status="published",
            published_at=now,
        )
        db.add(role)
        await db.flush()
        rule_set = EligibilityRuleSet(
            institution_id=institution.id,
            role_id=role.id,
            version=1,
            status="published",
            rules=rules,
            created_by_user_id=admin.id,
            published_at=now,
        )
        db.add(rule_set)
        await db.flush()
        evaluation = EligibilityEvaluation(
            institution_id=institution.id,
            role_id=role.id,
            student_user_id=student.id,
            rule_set_id=rule_set.id,
            facts_snapshot=facts,
            result_snapshot=eligibility,
            fingerprint="b" * 64,
            created_at=now,
        )
        db.add(evaluation)
        await db.flush()
        application = Application(
            institution_id=institution.id,
            role_id=role.id,
            student_user_id=student.id,
            resume_version_id=resume.id,
            eligibility_evaluation_id=evaluation.id,
            idempotency_key="recovery-fixture-v1",
            role_snapshot=role_snapshot,
            resume_snapshot=resume_snapshot,
            facts_snapshot=facts,
            rule_snapshot=rule_snapshot,
            eligibility_snapshot=eligibility,
        )
        db.add(application)
        await db.flush()
        db.add(
            AuditEvent(
                actor_user_id=admin.id,
                institution_id=institution.id,
                event_type="recovery.fixture.created",
                resource_type="application",
                resource_id=str(application.id),
                correlation_id="phase7d-recovery-fixture",
                details={"data_class": "synthetic-only", "snapshot_hash": snapshot_hash},
            )
        )
        await db.commit()
    return {
        "data_class": "synthetic-only",
        "application_snapshot_hash": snapshot_hash,
        "object_reference": resume.storage_key,
    }


def main() -> None:
    print(json.dumps(asyncio.run(seed()), sort_keys=True))


if __name__ == "__main__":
    main()
