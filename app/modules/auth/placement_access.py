"""Deterministic, institution-scoped student placement access policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.auth import Institution
from app.models.profile import StudentProfile

STANDARD_PROGRAM_DURATION_YEARS = 4
PLACEMENT_ACCESS_STUDY_YEARS = frozenset({3, 4})
_PRN_PATTERN = re.compile(r"(?P<prefix>1\d{2})[A-Z0-9]+", re.IGNORECASE)


@dataclass(frozen=True)
class PlacementAccessCapability:
    available: bool
    study_year: int | None
    academic_year_start: int | None
    reason: str | None = None


def parse_admission_year(prn: str | None) -> int:
    """Parse the admission year encoded in a conventional 1YY PRN prefix."""
    if not isinstance(prn, str):
        raise ValueError("invalid_prn")
    match = _PRN_PATTERN.fullmatch(prn.strip())
    if match is None:
        raise ValueError("invalid_prn")
    prefix = match.group("prefix")
    return 2000 + int(prefix[1:])


def normalize_prn(prn: str) -> str:
    normalized = prn.strip().upper()
    parse_admission_year(normalized)
    return normalized


def current_academic_year_start(
    institution: Institution, *, now: datetime | None = None
) -> int | None:
    """Return this institution's academic-year start year in its local timezone."""
    try:
        timezone = ZoneInfo(institution.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    local_now = (now or datetime.now(UTC)).astimezone(timezone)
    return local_now.year if local_now.month >= institution.academic_year_start_month else local_now.year - 1


def derive_placement_access(
    profile: StudentProfile | None,
    institution: Institution | None,
    *,
    now: datetime | None = None,
) -> PlacementAccessCapability:
    if profile is None:
        return PlacementAccessCapability(False, None, None, "profile_missing")
    if institution is None or profile.institution_id != institution.id:
        return PlacementAccessCapability(False, None, None, "institution_unavailable")
    if not 1 <= institution.academic_year_start_month <= 12:
        return PlacementAccessCapability(False, None, None, "academic_configuration_invalid")
    academic_year_start = current_academic_year_start(institution, now=now)
    if academic_year_start is None:
        return PlacementAccessCapability(False, None, None, "academic_configuration_invalid")
    try:
        admission_year = parse_admission_year(profile.prn)
    except ValueError:
        return PlacementAccessCapability(
            False, None, academic_year_start, "student_prn_invalid_or_missing"
        )
    study_year = academic_year_start - admission_year + 1
    if study_year < 1:
        return PlacementAccessCapability(False, study_year, academic_year_start, "future_admission_year")
    if study_year > STANDARD_PROGRAM_DURATION_YEARS:
        return PlacementAccessCapability(False, study_year, academic_year_start, "program_complete")
    if profile.prn_verified_at is None:
        return PlacementAccessCapability(
            False, study_year, academic_year_start, "student_prn_verification_required"
        )
    return PlacementAccessCapability(
        study_year in PLACEMENT_ACCESS_STUDY_YEARS,
        study_year,
        academic_year_start,
        None if study_year in PLACEMENT_ACCESS_STUDY_YEARS else "study_year_not_eligible",
    )


def unavailable_capability() -> PlacementAccessCapability:
    return PlacementAccessCapability(False, None, None, "student_placement_access_unavailable")
