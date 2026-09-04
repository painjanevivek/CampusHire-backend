"""Seed a deterministic, synthetic-only dataset for the CampusHire product video.

This script is intentionally restricted to an enabled local development environment.
It keeps video fixtures in their own institution so existing development and QA data
remain untouched, and it is safe to run repeatedly before a screen-capture session.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.models.auth import (
    Institution,
    InstitutionMembership,
    MembershipStatus,
    User,
    UserRole,
)
from app.models.engagement import RoadmapProgress, RoadmapTemplate, StudentRoadmap
from app.models.intelligence import PolicyDocument, ReviewStatus, SemanticMatchEvidence
from app.models.profile import StudentProfile
from app.models.recruitment import (
    Application,
    Company,
    EligibilityRuleSet,
    PlacementDrive,
    PlacementRole,
    PublicationStatus,
    RuleSetStatus,
    SavedOpportunity,
)
from app.models.resume import Resume, ResumeStatus, ResumeVersion, ScanStatus
from app.modules.auth.security import hash_password
from app.modules.engagement.service import ensure_templates, upsert_notification
from app.modules.recruitment.schemas import ApplicationCreate, ApplicationStatusUpdate
from app.modules.recruitment.service import create_application, update_application_status

VIDEO_INSTITUTION_CODE = "video-local"
VIDEO_INSTITUTION_NAME = "Riverview Institute of Technology"


@dataclass(frozen=True)
class RoleSpec:
    company_name: str
    company_description: str
    website_url: str
    drive_title: str
    role_title: str
    role_description: str
    location: str
    work_mode: str
    salary: str
    skills: list[str]
    requirements: list[str]
    deadline_days: int
    match_score: int


def _fingerprint(value: str) -> str:
    return hashlib.sha256(f"campushire-video:{value}".encode()).hexdigest()


async def _upsert_user(
    *,
    institution: Institution,
    email: str,
    password: str,
    role: UserRole,
) -> User:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password), role=role.value)
            db.add(user)
            await db.flush()

        user.institution_id = institution.id
        user.password_hash = hash_password(password)
        user.role = role.value
        user.is_active = True
        user.failed_login_count = 0
        user.locked_until = None

        membership = await db.scalar(
            select(InstitutionMembership).where(
                InstitutionMembership.institution_id == institution.id,
                InstitutionMembership.user_id == user.id,
            )
        )
        if membership is None:
            membership = InstitutionMembership(
                institution_id=institution.id,
                user_id=user.id,
                role=role.value,
                status=MembershipStatus.ACTIVE.value,
                verified_at=datetime.now(UTC),
                verified_by_user_id=user.id,
            )
            db.add(membership)
        else:
            membership.role = role.value
            membership.status = MembershipStatus.ACTIVE.value
            membership.verified_at = membership.verified_at or datetime.now(UTC)

        await db.commit()
        await db.refresh(user)
        return user


async def _upsert_profile(
    *,
    user: User,
    institution: Institution,
    full_name: str,
    prn: str,
    department: str,
    target_roles: list[str],
    skills: list[str],
    score: float,
) -> StudentProfile:
    async with SessionFactory() as db:
        profile = await db.scalar(select(StudentProfile).where(StudentProfile.user_id == user.id))
        if profile is None:
            profile = StudentProfile(user_id=user.id)
            db.add(profile)

        profile.institution_id = institution.id
        profile.full_name = full_name
        profile.institution_name = institution.name
        profile.prn = prn
        profile.department = department
        profile.academic_year = "Final year"
        profile.phone = "+91 98765 43210"
        profile.city = "Pune"
        profile.country_code = "IN"
        profile.education = [
            {
                "degree": "B.Tech",
                "branch": department,
                "institution": institution.name,
                "start_year": 2023,
                "graduation_year": 2027,
                "score": score,
                "score_scale": "cgpa_10",
            }
        ]
        profile.skills = [
            {"name": skill, "proficiency": "strong" if index < 3 else "working"}
            for index, skill in enumerate(skills)
        ]
        profile.target_roles = target_roles
        profile.external_links = {
            "github": f"https://github.com/{full_name.lower().replace(' ', '-')}"
        }
        profile.onboarding_step = 8
        profile.revision = max(profile.revision or 1, 3)
        await db.commit()
        await db.refresh(profile)
        return profile


async def _upsert_resume(*, student: User, institution: Institution) -> ResumeVersion:
    async with SessionFactory() as db:
        resume = await db.scalar(select(Resume).where(Resume.user_id == student.id))
        if resume is None:
            resume = Resume(
                user_id=student.id,
                institution_id=institution.id,
                latest_version_number=1,
            )
            db.add(resume)
            await db.flush()
        else:
            resume.institution_id = institution.id
            resume.latest_version_number = max(resume.latest_version_number, 1)

        checksum = _fingerprint("aarav-resume-v1")
        version = await db.scalar(
            select(ResumeVersion).where(
                ResumeVersion.user_id == student.id,
                ResumeVersion.checksum == checksum,
            )
        )
        if version is None:
            version = ResumeVersion(
                resume_id=resume.id,
                user_id=student.id,
                institution_id=institution.id,
                version_number=1,
                source="generated",
                storage_key=f"video-demo/{student.id}/aarav-sharma-resume.pdf",
                original_name="Aarav-Sharma-Resume.pdf",
                checksum=checksum,
                content_type="application/pdf",
                size_bytes=184_320,
                created_at=datetime.now(UTC) - timedelta(days=12),
            )

        version.resume_id = resume.id
        version.institution_id = institution.id
        version.status = ResumeStatus.COMPLETED.value
        version.scan_status = ScanStatus.CLEAN.value
        version.scan_engine = "CampusHire Safe Upload"
        version.scanned_at = datetime.now(UTC) - timedelta(days=12)
        version.page_count = 1
        version.extracted_text = (
            "Reviewed synthetic resume for the CampusHire product demonstration."
        )
        version.extracted_data = {
            "summary": (
                "Final-year computer science student building dependable web products and APIs."
            ),
            "skills": ["TypeScript", "React", "Python", "FastAPI", "PostgreSQL"],
            "projects": [
                {
                    "name": "QueueWise",
                    "description": (
                        "Built a campus service queue platform used in a simulated "
                        "500-student pilot."
                    ),
                    "technologies": ["React", "FastAPI", "PostgreSQL"],
                    "link": "https://github.com/aarav-sharma/queuewise",
                },
                {
                    "name": "SpendScope",
                    "description": (
                        "Created a privacy-first expense insights dashboard with tested APIs."
                    ),
                    "technologies": ["TypeScript", "Python"],
                    "link": "https://github.com/aarav-sharma/spendscope",
                },
            ],
            "education": ["B.Tech Computer Science — CGPA 8.6"],
            "experience": ["Software engineering intern — 12 weeks"],
        }
        version.review_revision = 2
        version.review_completed_at = datetime.now(UTC) - timedelta(days=11)
        db.add(version)
        await db.commit()
        await db.refresh(version)
        return version


async def _upsert_policy(*, institution: Institution, admin: User) -> PolicyDocument:
    async with SessionFactory() as db:
        policy = await db.scalar(
            select(PolicyDocument).where(
                PolicyDocument.institution_id == institution.id,
                PolicyDocument.title == "Campus Placement Eligibility Policy",
                PolicyDocument.version == 1,
            )
        )
        if policy is None:
            policy = PolicyDocument(
                institution_id=institution.id,
                title="Campus Placement Eligibility Policy",
                version=1,
                source_reference="RIT/TNP/PLACEMENT/2027",
                sections=[],
                created_by_user_id=admin.id,
            )
            db.add(policy)
        policy.sections = [
            {
                "heading": "Academic eligibility",
                "body": (
                    "Participating employers may publish degree, graduation-year, and "
                    "minimum-CGPA requirements before applications open."
                ),
            },
            {
                "heading": "Evidence and review",
                "body": (
                    "Eligibility uses institution-verified profile facts and a clean, "
                    "student-reviewed resume version."
                ),
            },
            {
                "heading": "Transparent decisions",
                "body": (
                    "Students can view the published rules, retained decision evidence, "
                    "and append-only status history for each application."
                ),
            },
        ]
        policy.status = ReviewStatus.APPROVED.value
        policy.reviewed_by_user_id = admin.id
        policy.review_reason = "Approved for the synthetic product demonstration"
        policy.approved_at = policy.approved_at or datetime.now(UTC) - timedelta(days=30)
        await db.commit()
        await db.refresh(policy)
        return policy


async def _upsert_role(
    *,
    institution: Institution,
    admin: User,
    company_name: str,
    company_description: str,
    website_url: str,
    drive_title: str,
    role_title: str,
    role_description: str,
    location: str,
    work_mode: str,
    salary: str,
    skills: list[str],
    requirements: list[str],
    deadline_days: int,
) -> PlacementRole:
    async with SessionFactory() as db:
        now = datetime.now(UTC)
        company = await db.scalar(
            select(Company).where(
                Company.institution_id == institution.id,
                Company.name == company_name,
            )
        )
        if company is None:
            company = Company(institution_id=institution.id, name=company_name)
            db.add(company)
            await db.flush()
        company.website_url = website_url
        company.description = company_description
        company.status = "active"

        drive = await db.scalar(
            select(PlacementDrive).where(
                PlacementDrive.institution_id == institution.id,
                PlacementDrive.title == drive_title,
            )
        )
        if drive is None:
            drive = PlacementDrive(
                institution_id=institution.id,
                company_id=company.id,
                title=drive_title,
                description=role_description,
                location=location,
                work_mode=work_mode,
                opens_at=now - timedelta(days=2),
                deadline_at=now + timedelta(days=deadline_days),
            )
            db.add(drive)
            await db.flush()
        drive.company_id = company.id
        drive.description = (
            f"{company_name} is hiring final-year students through a reviewed campus process."
        )
        drive.location = location
        drive.work_mode = work_mode
        drive.opens_at = now - timedelta(days=2)
        drive.deadline_at = now + timedelta(days=deadline_days)
        drive.status = PublicationStatus.PUBLISHED.value
        drive.published_at = drive.published_at or now - timedelta(days=2)

        role = await db.scalar(
            select(PlacementRole).where(
                PlacementRole.institution_id == institution.id,
                PlacementRole.drive_id == drive.id,
                PlacementRole.title == role_title,
            )
        )
        if role is None:
            role = PlacementRole(
                institution_id=institution.id,
                drive_id=drive.id,
                title=role_title,
                description=role_description,
                employment_type="full-time",
                location=location,
                work_mode=work_mode,
            )
            db.add(role)
            await db.flush()
        role.description = role_description
        role.location = location
        role.work_mode = work_mode
        role.salary_display = salary
        role.skills = skills
        role.requirements = requirements
        role.status = PublicationStatus.PUBLISHED.value
        role.published_at = role.published_at or now - timedelta(days=2)

        rule_set = await db.scalar(
            select(EligibilityRuleSet).where(
                EligibilityRuleSet.role_id == role.id,
                EligibilityRuleSet.status == RuleSetStatus.PUBLISHED.value,
            )
        )
        rules: list[dict[str, Any]] = [
            {"field": "degree", "operator": "eq", "value": "B.Tech", "label": "Degree"},
            {
                "field": "cgpa",
                "operator": "gte",
                "value": 7.0,
                "label": "Minimum CGPA",
            },
            {
                "field": "graduation_year",
                "operator": "eq",
                "value": 2027,
                "label": "Graduation year",
            },
            {"field": "resume", "operator": "eq", "value": True, "label": "Reviewed resume"},
        ]
        if rule_set is None:
            rule_set = EligibilityRuleSet(
                institution_id=institution.id,
                role_id=role.id,
                version=1,
                created_by_user_id=admin.id,
            )
            db.add(rule_set)
        rule_set.rules = rules
        rule_set.policy_references = []
        rule_set.status = RuleSetStatus.PUBLISHED.value
        rule_set.published_at = rule_set.published_at or now - timedelta(days=2)
        await db.commit()
        await db.refresh(role)
        return role


async def _upsert_match(
    *,
    institution: Institution,
    student: User,
    resume: ResumeVersion,
    profile: StudentProfile,
    role: PlacementRole,
    score: int,
) -> None:
    async with SessionFactory() as db:
        fingerprint = _fingerprint(f"match:{student.id}:{role.id}:v1")
        item = await db.scalar(
            select(SemanticMatchEvidence).where(
                SemanticMatchEvidence.institution_id == institution.id,
                SemanticMatchEvidence.fingerprint == fingerprint,
            )
        )
        if item is None:
            item = SemanticMatchEvidence(
                institution_id=institution.id,
                student_user_id=student.id,
                role_id=role.id,
                resume_version_id=resume.id,
                profile_revision=profile.revision,
                fingerprint=fingerprint,
                status="available",
                score=score,
                components={},
                explanation=[],
                embedding_model="demo-reviewed-evidence",
                embedding_version="v1",
                scoring_version="match-v1",
                created_at=datetime.now(UTC),
            )
            db.add(item)
        item.status = "available"
        item.score = score
        item.components = {
            "skills": score / 100,
            "target_role": 0.92,
            "project_evidence": 0.88,
        }
        item.explanation = [
            "Your reviewed project evidence matches the role's core engineering work.",
            "Your selected target role and required technical skills align strongly.",
        ]
        await db.commit()


async def _upsert_application(
    *,
    institution: Institution,
    student: User,
    admin: User,
    resume: ResumeVersion,
    role: PlacementRole,
    target_status: str,
) -> Application:
    async with SessionFactory() as db:
        application = await db.scalar(
            select(Application).where(
                Application.student_user_id == student.id,
                Application.role_id == role.id,
            )
        )
        if application is None:
            application, _ = await create_application(
                db,
                institution.id,
                student.id,
                f"video-{role.id}",
                ApplicationCreate(role_id=role.id, resume_version_id=resume.id),
            )

        transitions = {
            "under_review": ["under_review"],
            "shortlisted": ["under_review", "shortlisted"],
            "interview": ["under_review", "shortlisted", "interview"],
        }
        ordered_statuses = transitions.get(target_status, [])
        for status in ordered_statuses:
            if application.status == status:
                continue
            allowed_previous = {
                "under_review": "submitted",
                "shortlisted": "under_review",
                "interview": "shortlisted",
            }
            if application.status != allowed_previous[status]:
                continue
            application = await update_application_status(
                db,
                institution.id,
                application.id,
                admin.id,
                ApplicationStatusUpdate(
                    status=status,
                    reason=(
                        "Reviewed against the published role criteria"
                        if status == "under_review"
                        else "Selected for the next stage of the campus process"
                    ),
                ),
            )
        await db.commit()
        await db.refresh(application)
        return application


async def _seed_roadmap_and_notifications(
    *,
    institution: Institution,
    student: User,
    admin: User,
) -> None:
    async with SessionFactory() as db:
        await ensure_templates(db)
        template = await db.scalar(
            select(RoadmapTemplate).where(
                RoadmapTemplate.title == "Software Developer",
                RoadmapTemplate.status == "approved",
            )
        )
        if template is None:
            raise RuntimeError("The curated Software Developer roadmap was not created")
        roadmap = await db.scalar(
            select(StudentRoadmap).where(StudentRoadmap.student_user_id == student.id)
        )
        if roadmap is None:
            roadmap = StudentRoadmap(
                institution_id=institution.id,
                student_user_id=student.id,
                template_id=template.id,
            )
            db.add(roadmap)
            await db.flush()
        else:
            roadmap.institution_id = institution.id
            roadmap.template_id = template.id

        first_node = str(template.nodes[0]["key"])
        progress = await db.scalar(
            select(RoadmapProgress).where(
                RoadmapProgress.student_roadmap_id == roadmap.id,
                RoadmapProgress.node_key == first_node,
            )
        )
        if progress is None:
            progress = RoadmapProgress(student_roadmap_id=roadmap.id, node_key=first_node)
            db.add(progress)
        progress.status = "completed"
        progress.evidence = {
            "label": "QueueWise project repository",
            "reference": "Reviewed project evidence",
        }
        progress.completed_at = datetime.now(UTC) - timedelta(days=4)

        notices = [
            (
                "video:application-shortlisted",
                "You’ve been shortlisted",
                "Northstar Labs has moved your application to the shortlisted stage.",
                "/applications",
                None,
            ),
            (
                "video:deadline-reminder",
                "Application deadline in 6 days",
                "The Meridian Systems graduate programme is still open for eligible students.",
                "/opportunities",
                datetime.now(UTC) - timedelta(days=1),
            ),
            (
                "video:roadmap-progress",
                "Your next roadmap milestone is ready",
                "Continue with Problem-solving work when you are ready.",
                "/roadmap",
                datetime.now(UTC) - timedelta(days=2),
            ),
        ]
        for event_key, title, body, deep_link, read_at in notices:
            notice = await upsert_notification(
                db,
                institution_id=institution.id,
                recipient_user_id=student.id,
                event_key=event_key,
                title=title,
                body=body,
                deep_link=deep_link,
                created_by_user_id=admin.id,
            )
            notice.read_at = read_at
        await db.commit()


async def seed() -> dict[str, object]:
    settings = get_settings()
    if not settings.demo_login_enabled or not settings.is_development:
        raise RuntimeError("Video fixtures require DEMO_LOGIN_ENABLED in local development")
    if (
        settings.demo_student_email is None
        or settings.demo_student_password is None
        or settings.demo_admin_email is None
        or settings.demo_admin_password is None
    ):
        raise RuntimeError("Configure both synthetic demo accounts before seeding video fixtures")

    async with SessionFactory() as db:
        institution = await db.scalar(
            select(Institution).where(Institution.code == VIDEO_INSTITUTION_CODE)
        )
        if institution is None:
            institution = Institution(code=VIDEO_INSTITUTION_CODE, name=VIDEO_INSTITUTION_NAME)
            db.add(institution)
        institution.name = VIDEO_INSTITUTION_NAME
        institution.is_active = True
        institution.roadmaps_enabled = True
        institution.timezone = "Asia/Kolkata"
        await db.commit()
        await db.refresh(institution)

    student = await _upsert_user(
        institution=institution,
        email=str(settings.demo_student_email),
        password=settings.demo_student_password.get_secret_value(),
        role=UserRole.STUDENT,
    )
    admin = await _upsert_user(
        institution=institution,
        email=str(settings.demo_admin_email),
        password=settings.demo_admin_password.get_secret_value(),
        role=UserRole.TNP_ADMIN,
    )
    profile = await _upsert_profile(
        user=student,
        institution=institution,
        full_name="Aarav Sharma",
        prn="RIT-2027-CS-042",
        department="Computer Science",
        target_roles=["Software Developer"],
        skills=["TypeScript", "React", "Python", "FastAPI", "PostgreSQL"],
        score=8.6,
    )

    supporting_students = [
        ("meera.video@example.com", "Meera Nair", "RIT-2027-CS-018", 9.1),
        ("kabir.video@example.com", "Kabir Mehta", "RIT-2027-CS-031", 8.2),
        ("isha.video@example.com", "Isha Kulkarni", "RIT-2027-IT-014", 8.8),
    ]
    for email, full_name, prn, score in supporting_students:
        supporting_user = await _upsert_user(
            institution=institution,
            email=email,
            password=settings.demo_student_password.get_secret_value(),
            role=UserRole.STUDENT,
        )
        await _upsert_profile(
            user=supporting_user,
            institution=institution,
            full_name=full_name,
            prn=prn,
            department="Computer Science",
            target_roles=["Software Developer"],
            skills=["Python", "SQL", "React"],
            score=score,
        )

    resume = await _upsert_resume(student=student, institution=institution)
    await _upsert_policy(institution=institution, admin=admin)
    role_specs = [
        RoleSpec(
            company_name="Northstar Labs",
            company_description=(
                "A Bengaluru product studio building dependable workflow software."
            ),
            website_url="https://example.com/northstar-labs",
            drive_title="Northstar Graduate Engineering 2027",
            role_title="Graduate Software Engineer",
            role_description=(
                "Build and ship reliable product features across React, TypeScript, "
                "Python, and APIs."
            ),
            location="Bengaluru, India",
            work_mode="hybrid",
            salary="INR 12–14 LPA",
            skills=["TypeScript", "React", "Python", "PostgreSQL"],
            requirements=["B.Tech", "CGPA 7.0 or above", "Graduating in 2027"],
            deadline_days=12,
            match_score=92,
        ),
        RoleSpec(
            company_name="Meridian Systems",
            company_description=(
                "An enterprise technology company modernising financial operations."
            ),
            website_url="https://example.com/meridian-systems",
            drive_title="Meridian Technology Programme 2027",
            role_title="Associate Backend Engineer",
            role_description=(
                "Design secure services, observable APIs, and data workflows used by "
                "operations teams."
            ),
            location="Pune, India",
            work_mode="hybrid",
            salary="INR 10–12 LPA",
            skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
            requirements=["B.Tech", "CGPA 7.0 or above", "Graduating in 2027"],
            deadline_days=18,
            match_score=88,
        ),
        RoleSpec(
            company_name="Fieldnote Technologies",
            company_description="A remote-first SaaS company for distributed field teams.",
            website_url="https://example.com/fieldnote-technologies",
            drive_title="Fieldnote Campus Product Hiring 2027",
            role_title="Frontend Product Engineer",
            role_description=(
                "Create accessible, responsive interfaces with React, TypeScript, "
                "and a strong testing culture."
            ),
            location="Remote — India",
            work_mode="remote",
            salary="INR 11–13 LPA",
            skills=["TypeScript", "React", "Accessibility", "Testing"],
            requirements=["B.Tech", "CGPA 7.0 or above", "Graduating in 2027"],
            deadline_days=24,
            match_score=85,
        ),
    ]
    roles: list[PlacementRole] = []
    for spec in role_specs:
        role = await _upsert_role(
            institution=institution,
            admin=admin,
            company_name=spec.company_name,
            company_description=spec.company_description,
            website_url=spec.website_url,
            drive_title=spec.drive_title,
            role_title=spec.role_title,
            role_description=spec.role_description,
            location=spec.location,
            work_mode=spec.work_mode,
            salary=spec.salary,
            skills=spec.skills,
            requirements=spec.requirements,
            deadline_days=spec.deadline_days,
        )
        await _upsert_match(
            institution=institution,
            student=student,
            resume=resume,
            profile=profile,
            role=role,
            score=spec.match_score,
        )
        roles.append(role)

    first_application = await _upsert_application(
        institution=institution,
        student=student,
        admin=admin,
        resume=resume,
        role=roles[0],
        target_status="shortlisted",
    )
    second_application = await _upsert_application(
        institution=institution,
        student=student,
        admin=admin,
        resume=resume,
        role=roles[1],
        target_status="under_review",
    )

    async with SessionFactory() as db:
        saved = await db.scalar(
            select(SavedOpportunity).where(
                SavedOpportunity.student_user_id == student.id,
                SavedOpportunity.role_id == roles[2].id,
            )
        )
        if saved is None:
            db.add(
                SavedOpportunity(
                    institution_id=institution.id,
                    student_user_id=student.id,
                    role_id=roles[2].id,
                    created_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
        await db.commit()

    await _seed_roadmap_and_notifications(
        institution=institution,
        student=student,
        admin=admin,
    )
    return {
        "institution": institution.name,
        "student": student.email,
        "admin": admin.email,
        "roles": [role.title for role in roles],
        "applications": [str(first_application.id), str(second_application.id)],
        "data_class": "synthetic-only",
    }


def main() -> None:
    print(json.dumps(asyncio.run(seed()), sort_keys=True))


if __name__ == "__main__":
    main()
