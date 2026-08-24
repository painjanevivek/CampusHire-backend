from __future__ import annotations

import asyncio
import json
import os

from sqlalchemy import select

from app.core.database import SessionFactory
from app.models.auth import (
    Institution,
    InstitutionMembership,
    MembershipStatus,
    User,
    UserRole,
)
from app.modules.auth.security import hash_password


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} to a synthetic staging credential.")
    return value


async def ensure_user(email: str, password: str, role: UserRole) -> User:
    async with SessionFactory() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password), role=role.value)
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user


async def ensure_institution(code: str, name: str) -> Institution:
    async with SessionFactory() as db:
        institution = await db.scalar(select(Institution).where(Institution.code == code))
        if institution is None:
            institution = Institution(code=code, name=name)
            db.add(institution)
            await db.commit()
            await db.refresh(institution)
        return institution


async def ensure_membership(
    institution: Institution,
    user: User,
    role: UserRole,
    verifier: User,
) -> None:
    async with SessionFactory() as db:
        membership = await db.scalar(
            select(InstitutionMembership).where(
                InstitutionMembership.institution_id == institution.id,
                InstitutionMembership.user_id == user.id,
            )
        )
        if membership is None:
            db.add(
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=user.id,
                    role=role.value,
                    status=MembershipStatus.ACTIVE.value,
                    verified_by_user_id=verifier.id,
                )
            )
            await db.commit()


async def seed() -> dict[str, str]:
    student_email = os.getenv("STAGING_STUDENT_EMAIL", "student+synthetic-a@example.com")
    admin_email = os.getenv("STAGING_ADMIN_EMAIL", "admin+synthetic-a@example.com")
    second_admin_email = os.getenv("STAGING_SECOND_ADMIN_EMAIL", "admin+synthetic-b@example.com")
    student = await ensure_user(
        student_email, required("STAGING_STUDENT_PASSWORD"), UserRole.STUDENT
    )
    admin = await ensure_user(admin_email, required("STAGING_ADMIN_PASSWORD"), UserRole.TNP_ADMIN)
    second_admin = await ensure_user(
        second_admin_email,
        required("STAGING_SECOND_ADMIN_PASSWORD"),
        UserRole.TNP_ADMIN,
    )
    first = await ensure_institution("synthetic-a", "Synthetic Campus A")
    second = await ensure_institution("synthetic-b", "Synthetic Campus B")
    await ensure_membership(first, admin, UserRole.TNP_ADMIN, admin)
    await ensure_membership(first, student, UserRole.STUDENT, admin)
    await ensure_membership(second, second_admin, UserRole.TNP_ADMIN, second_admin)
    return {
        "student_email": student.email,
        "admin_email": admin.email,
        "first_institution_id": str(first.id),
        "second_institution_id": str(second.id),
        "data_class": "synthetic-only",
    }


def main() -> None:
    print(json.dumps(asyncio.run(seed()), sort_keys=True))


if __name__ == "__main__":
    main()
