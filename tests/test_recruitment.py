from datetime import UTC, datetime, timedelta

import pytest

from app.modules.recruitment.domain import (
    ApplicationStatus,
    DriveStatus,
    can_apply,
    validate_transition,
)


def test_only_open_drives_before_deadline_accept_applications() -> None:
    now = datetime.now(UTC)
    assert can_apply(DriveStatus.OPEN, now + timedelta(hours=1), now)
    assert not can_apply(DriveStatus.DRAFT, now + timedelta(hours=1), now)
    assert not can_apply(DriveStatus.OPEN, now - timedelta(seconds=1), now)


def test_application_history_rejects_invalid_transition() -> None:
    validate_transition(ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_REVIEW)
    with pytest.raises(ValueError):
        validate_transition(ApplicationStatus.SUBMITTED, ApplicationStatus.OFFERED)
