from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.models.auth import Institution
from app.models.profile import StudentProfile
from app.modules.auth.institutional_identity import (
    InstitutionalEmailError,
    normalize_pccoe_email,
    validate_pcco_email_prn_consistency,
)
from app.modules.auth.placement_access import derive_placement_access, parse_admission_year


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("name.surname23@pccoepune.org", 2023),
        ("firstname.lastname24@pccoepune.org", 2024),
        ("NAME.SURNAME23@PCCOEPUNE.ORG", 2023),
        ("a23@pccoepune.org", 2023),
    ],
)
def test_pccoe_email_is_normalized_and_batch_year_extracted(email: str, expected: int) -> None:
    normalized, admission_year = normalize_pccoe_email(email)
    assert normalized == email.strip().casefold()
    assert admission_year == expected


@pytest.mark.parametrize(
    "email",
    [
        "name.surname@gmail.com",
        "name.surname23@gmail.com",
        "name.surname@pccoepune.org",
        "random@pccoepune.org",
        "not an email",
        "name.surname27@pccoepune.org",
    ],
)
def test_invalid_pccoe_emails_are_rejected(email: str) -> None:
    with pytest.raises(InstitutionalEmailError):
        normalize_pccoe_email(email)


@pytest.mark.parametrize(
    ("batch", "expected"), [("123B1B287", 2023), ("124B1B287", 2024), ("125B1B287", 2025)]
)
def test_prn_parser_extracts_admission_year(batch: str, expected: int) -> None:
    assert parse_admission_year(batch) == expected


def test_email_and_prn_admission_years_must_match() -> None:
    validate_pcco_email_prn_consistency("name.surname23@pccoepune.org", "123B1B287")
    with pytest.raises(InstitutionalEmailError, match="does not match your PRN"):
        validate_pcco_email_prn_consistency("name.surname23@pccoepune.org", "124B1B287")


@pytest.mark.parametrize(
    ("admission_year", "academic_start", "allowed", "study_year"),
    [
        (2023, 2026, True, 4),
        (2024, 2026, True, 3),
        (2025, 2026, False, 2),
        (2026, 2026, False, 1),
        (2023, 2027, False, 5),
        (2027, 2026, False, -0),
    ],
)
def test_placement_access_uses_configured_academic_year(
    admission_year: int, academic_start: int, allowed: bool, study_year: int
) -> None:
    institution = Institution(
        code="pccoe",
        name="PCCOE",
        timezone="UTC",
        academic_year_start_month=6,
    )
    profile = StudentProfile(
        user_id=uuid4(),
        institution_id=institution.id,
        prn=f"1{admission_year % 100:02d}B1B287",
        prn_verified_at=datetime(academic_start, 7, 1, tzinfo=UTC),
        prn_verified_by_user_id=uuid4(),
    )
    result = derive_placement_access(
        profile,
        institution,
        now=datetime(academic_start, 7, 1, tzinfo=UTC),
    )
    assert result.available is allowed
    assert result.study_year == study_year
    assert result.academic_year_start == academic_start


def test_placement_access_fails_closed_for_missing_or_invalid_prn() -> None:
    institution = Institution(
        code="pccoe", name="PCCOE", timezone="UTC", academic_year_start_month=6
    )
    for prn in (None, "invalid"):
        result = derive_placement_access(
            StudentProfile(user_id=uuid4(), institution_id=institution.id, prn=prn),
            institution,
            now=datetime(2026, 7, 1, tzinfo=UTC),
        )
        assert not result.available
        assert result.reason == "student_prn_invalid_or_missing"


def test_pccoe_domain_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(
        update={"pccoe_student_email_domain": "students.example.edu"}
    )
    monkeypatch.setattr("app.modules.auth.institutional_identity.get_settings", lambda: settings)
    assert normalize_pccoe_email("student23@STUDENTS.EXAMPLE.EDU")[1] == 2023
