"""Seed explicitly configured synthetic accounts for local demo login."""

from __future__ import annotations

import asyncio
import json

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
from app.modules.auth.security import hash_password


async def ensure_demo_user(
    institution: Institution,
    *,
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
                verified_by_user_id=user.id,
            )
            db.add(membership)
        elif membership.role != role.value:
            raise RuntimeError(f"Configured demo account {email} has the wrong institutional role")
        user.password_hash = hash_password(password)
        user.role = role.value
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
        password=settings.demo_student_password.get_secret_value(),
        role=UserRole.STUDENT,
    )
    admin = await ensure_demo_user(
        institution,
        email=str(settings.demo_admin_email),
        password=settings.demo_admin_password.get_secret_value(),
        role=UserRole.TNP_ADMIN,
    )
    return {
        "student_email": student.email,
        "admin_email": admin.email,
        "institution_id": str(institution.id),
        "data_class": "synthetic-only",
        "admin_next_step": "mfa_setup_or_challenge",
    }


def main() -> None:
    print(json.dumps(asyncio.run(seed()), sort_keys=True))


if __name__ == "__main__":
    main()
