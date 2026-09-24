from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.auth import Institution
from app.models.profile import StudentProfile
from app.modules.auth.placement_access import (
    current_academic_year_start,
    derive_placement_access,
    normalize_prn,
    parse_admission_year,
)
from app.modules.onboarding.schemas import StudentIdentityStep
from app.modules.profiles.schemas import IdentityUpdate, ProfileUpdate


def _student(prn: str | None, institution_id: object) -> StudentProfile:
    return StudentProfile(
        user_id=uuid4(),
        institution_id=institution_id,  # type: ignore[arg-type]
        prn=prn,
        prn_verified_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _institution(*, start_month: int = 6) -> Institution:
    return Institution(
        id=uuid4(), code="test-campus", name="Test Campus", timezone="Asia/Kolkata",
        academic_year_start_month=start_month,
    )


@pytest.mark.parametrize(
    ("prn", "expected_year", "expected_access"),
    [
        ("123B1B287", 4, True),
        ("124B1B287", 3, True),
        ("125B1B287", 2, False),
        ("126B1B287", 1, False),
    ],
)
def test_2026_academic_year_access_matrix(
    prn: str, expected_year: int, expected_access: bool
) -> None:
    institution = _institution()
    profile = _student(prn, institution.id)

    state = derive_placement_access(
        profile, institution, now=datetime(2026, 9, 24, tzinfo=UTC)
    )

    assert state.academic_year_start == 2026
    assert state.study_year == expected_year
    assert state.available is expected_access


@pytest.mark.parametrize(
    ("prn", "expected_year", "expected_access"),
    [
        ("124B1B287", 4, True),
        ("125B1B287", 3, True),
        ("126B1B287", 2, False),
        ("127B1B287", 1, False),
        ("123B1B287", 5, False),
    ],
)
def test_2027_transition_and_out_of_program_are_fail_closed(
    prn: str, expected_year: int, expected_access: bool
) -> None:
    institution = _institution()
    profile = _student(prn, institution.id)

    state = derive_placement_access(
        profile, institution, now=datetime(2027, 9, 24, tzinfo=UTC)
    )

    assert state.academic_year_start == 2027
    assert state.study_year == expected_year
    assert state.available is expected_access


@pytest.mark.parametrize("prn", [None, "", "PRN-001", "12B1B287", "999B1B287", "123-"])
def test_invalid_or_missing_prn_does_not_grant_access(prn: str | None) -> None:
    institution = _institution()

    state = derive_placement_access(
        _student(prn, institution.id), institution, now=datetime(2026, 9, 24, tzinfo=UTC)
    )

    assert state.available is False
    assert state.study_year is None
    if prn is not None:
        with pytest.raises(ValueError, match="invalid_prn"):
            parse_admission_year(prn)


def test_prn_parser_and_onboarding_validation_use_canonical_format() -> None:
    assert parse_admission_year("123b1b287") == 2023
    assert normalize_prn(" 123b1b287 ") == "123B1B287"
    with pytest.raises(ValidationError, match="registered format"):
        StudentIdentityStep(
            full_name="Student One",
            prn="PRN-001",
            department="Computer Engineering",
            graduation_year=2027,
        )
    with pytest.raises(ValidationError, match="registered format"):
        ProfileUpdate(prn="PRN-001")
    with pytest.raises(ValidationError, match="registered format"):
        IdentityUpdate(expected_revision=1, prn="PRN-001")


def test_institution_scope_and_calendar_configuration_fail_closed() -> None:
    institution = _institution()
    other_institution = _institution()
    profile = _student("124B1B287", other_institution.id)

    wrong_tenant = derive_placement_access(
        profile, institution, now=datetime(2026, 9, 24, tzinfo=UTC)
    )
    bad_calendar = _institution(start_month=13)
    invalid_calendar = derive_placement_access(
        _student("124B1B287", bad_calendar.id),
        bad_calendar,
        now=datetime(2026, 9, 24, tzinfo=UTC),
    )

    assert wrong_tenant.available is False
    assert wrong_tenant.study_year is None
    assert invalid_calendar.available is False
    assert current_academic_year_start(
        _institution(), now=datetime(2026, 5, 31, 10, tzinfo=UTC)
    ) == 2025


def test_format_valid_but_unverified_prn_does_not_grant_placement_access() -> None:
    institution = _institution()
    profile = _student("124B1B287", institution.id)
    profile.prn_verified_at = None

    state = derive_placement_access(
        profile, institution, now=datetime(2026, 9, 24, tzinfo=UTC)
    )

    assert state.available is False
    assert state.study_year == 3
    assert state.reason == "student_prn_verification_required"
