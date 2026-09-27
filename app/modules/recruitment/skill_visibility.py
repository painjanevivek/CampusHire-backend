"""Deterministic skill matching for student opportunity discovery.

This is a visibility rule, separate from published eligibility rules and advisory AI scores.
"""

import re
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import StudentProfile

_ALIASES = {
    "reactjs": "react",
    "nextjs": "nextjs",
    "vuejs": "vue",
    "angularjs": "angular",
    "html5": "html",
    "css3": "css",
    "js": "javascript",
    "ts": "typescript",
    "tailwindcss": "tailwind",
    "frontenddevelopment": "frontend",
    "frontendskills": "frontend",
    "frontendwebdevelopment": "frontend",
    "frontenddeveloper": "frontend",
    "frontendengineering": "frontend",
}
_FRONTEND_SKILLS = {
    "frontend", "react", "nextjs", "vue", "angular", "html", "css", "javascript",
    "typescript", "tailwind", "bootstrap", "svelte", "webdesign",
}


def _canonical_skill(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", value.casefold())
    return _ALIASES.get(compact, compact)


def matches_role_skills(
    role_skills: Iterable[str], student_skills: Iterable[Mapping[str, Any]]
) -> bool:
    """A role matches when any listed skill is evidenced by the student's profile.

    An empty role skill list places no visibility restriction. A broad Frontend tag
    accepts a specific frontend skill, but a generic tag does not prove React or Next.js.
    """
    required = {_canonical_skill(skill) for skill in role_skills if skill.strip()}
    if not required:
        return True
    recorded = {
        _canonical_skill(name)
        for item in student_skills
        if isinstance(item, Mapping)
        if isinstance(name := item.get("name"), str) and name.strip()
    }
    if required & recorded:
        return True
    return "frontend" in required and bool(recorded & _FRONTEND_SKILLS)


async def student_skill_items(
    db: AsyncSession, institution_id: UUID, student_user_id: UUID
) -> list[dict[str, Any]]:
    """Read skills only from the authenticated student's institution-scoped profile."""
    skills = await db.scalar(
        select(StudentProfile.skills).where(
            StudentProfile.user_id == student_user_id,
            StudentProfile.institution_id == institution_id,
        )
    )
    return skills if isinstance(skills, list) else []
