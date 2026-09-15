"""Seed explicitly configured synthetic accounts for local demo login."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.models.auth import (
    Institution,
    InstitutionMembership,
    MembershipStatus,
    MfaEnrollment,
    PlatformAdminAssignment,
    User,
    UserRole,
)
from app.modules.auth.security import hash_password, normalize_username
from app.modules.platform_admin.service import transfer_platform_admin


async def ensure_demo_user(
    institution: Institution,
    *,
    email: str,
    username: str | None,
    password: str,
    role: UserRole,
    institution_membership: bool = True,
) -> User:
    async with SessionFactory() as db:
        identity_filters = [User.email == email]
        if username is not None:
            identity_filters.append(User.username == username)
        user = await db.scalar(select(User).where(or_(*identity_filters)))
        if user is None:
            user = User(
                email=email,
                username=username,
                password_hash=hash_password(password),
                role=role.value,
            )
            db.add(user)
            await db.flush()
        membership = await db.scalar(
            select(InstitutionMembership).where(
                InstitutionMembership.institution_id == institution.id,
                InstitutionMembership.user_id == user.id,
            )
        )
        if membership is None and institution_membership:
            membership = InstitutionMembership(
                institution_id=institution.id,
                user_id=user.id,
                role=role.value,
                status=MembershipStatus.ACTIVE.value,
                verified_by_user_id=user.id,
            )
            db.add(membership)
        elif membership is not None and institution_membership:
            membership.role = role.value
            membership.status = MembershipStatus.ACTIVE.value
        elif membership is not None:
            membership.status = MembershipStatus.REVOKED.value
        user.email = email
        user.password_hash = hash_password(password)
        user.role = role.value
        user.username = username
        user.is_active = True
        await db.commit()
        await db.refresh(user)
        return user


async def seed() -> dict[str, str]:
    settings = get_settings()
    if not settings.demo_login_enabled or not settings.is_development:
        raise RuntimeError("Enable DEMO_LOGIN_ENABLED only in development or test before seeding")
    if (
        settings.demo_student_email is None
        or settings.demo_student_password is None
        or settings.demo_admin_email is None
        or settings.demo_admin_password is None
    ):
        raise RuntimeError("Configure both synthetic demo accounts before seeding")
    async with SessionFactory() as db:
        institution = await db.scalar(select(Institution).where(Institution.code == "demo-local"))
        if institution is None:
            institution = Institution(code="demo-local", name="CampusHire Demo Institution")
            db.add(institution)
            await db.commit()
            await db.refresh(institution)
    student = await ensure_demo_user(
        institution,
        email=str(settings.demo_student_email),
        username="demo-student",
        password=settings.demo_student_password.get_secret_value(),
        role=UserRole.STUDENT,
    )
    admin = await ensure_demo_user(
        institution,
        email=str(settings.demo_admin_email),
        username=normalize_username(settings.demo_admin_username),
        password=settings.demo_admin_password.get_secret_value(),
        role=UserRole.PLATFORM_ADMIN,
        institution_membership=False,
    )
    tnp_officer: User | None = None
    if settings.demo_tnp_email is not None and settings.demo_tnp_password is not None:
        tnp_officer = await ensure_demo_user(
            institution,
            email=str(settings.demo_tnp_email),
            username=normalize_username(settings.demo_tnp_username),
            password=settings.demo_tnp_password.get_secret_value(),
            role=UserRole.TNP_ADMIN,
        )
    async with SessionFactory() as db:
        active_enrollments = list(
            await db.scalars(
                select(MfaEnrollment).where(
                    MfaEnrollment.user_id == admin.id,
                    MfaEnrollment.enrolled_at.is_not(None),
                    MfaEnrollment.disabled_at.is_(None),
                )
            )
        )
        for enrollment in active_enrollments:
            enrollment.disabled_at = datetime.now(UTC)
        assignment = await db.scalar(select(PlatformAdminAssignment))
        await transfer_platform_admin(
            db,
            user_id=admin.id,
            reason="Assign the explicitly configured synthetic local Platform Admin.",
            actor_user_id=None,
            expected_revision=assignment.revision if assignment is not None else None,
        )
    return {
        "student_email": student.email,
        "tnp_email": tnp_officer.email if tnp_officer is not None else "not-configured",
        "tnp_workspace": "tnp" if tnp_officer is not None else "not-configured",
        "admin_email": admin.email,
        "admin_workspace": "platform_admin",
        "institution_id": str(institution.id),
        "data_class": "synthetic-only",
        "admin_next_step": "optional_mfa_available_in_account_settings",
    }


def main() -> None:
    print(json.dumps(asyncio.run(seed()), sort_keys=True))


if __name__ == "__main__":
    main()
