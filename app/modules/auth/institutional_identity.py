"""Deterministic policy for PCCOE student email and PRN identity."""

from __future__ import annotations

from datetime import datetime

from email_validator import EmailNotValidError, validate_email

from app.core.config import get_settings
from app.modules.auth.placement_access import parse_admission_year


class InstitutionalEmailError(ValueError):
    """A student email does not follow the configured PCCOE identity policy."""


_INVALID_EMAIL = "Enter a valid PCCOE student email containing the batch year."


def normalize_pccoe_email(value: str) -> tuple[str, int]:
    """Validate and normalize a PCCOE email, returning it with its admission year."""
    try:
        normalized = validate_email(value.strip(), check_deliverability=False).normalized.casefold()
    except (EmailNotValidError, AttributeError) as error:
        raise InstitutionalEmailError(_INVALID_EMAIL) from error

    expected_domain = get_settings().pccoe_student_email_domain.strip().casefold()
    local_part, separator, domain = normalized.rpartition("@")
    if not separator or domain != expected_domain:
        raise InstitutionalEmailError("Only PCCOE institutional email addresses are allowed.")
    if len(local_part) < 2 or not local_part[-2:].isdigit():
        raise InstitutionalEmailError(_INVALID_EMAIL)

    batch_year = int(local_part[-2:])
    admission_year = 2000 + batch_year
    if admission_year > datetime.now().year:
        raise InstitutionalEmailError(_INVALID_EMAIL)
    return normalized, admission_year


def validate_pcco_email_prn_consistency(email: str, prn: str | None) -> None:
    """Ensure an associated PCCOE email and PRN encode the same admission year."""
    normalized = email.strip().casefold()
    expected_domain = get_settings().pccoe_student_email_domain.strip().casefold()
    if normalized.rpartition("@")[2] != expected_domain:
        return
    _, email_year = normalize_pccoe_email(email)
    if not prn:
        return
    try:
        prn_year = parse_admission_year(prn)
    except ValueError as error:
        raise InstitutionalEmailError(
            "Enter a PRN in the institution's registered format."
        ) from error
    if email_year != prn_year:
        raise InstitutionalEmailError("The batch year in your PCCOE email does not match your PRN.")
