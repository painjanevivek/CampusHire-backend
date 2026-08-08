import pytest

from app.modules.notifications.domain import Notification, deduplicate, safe_deep_link


def test_retry_does_not_duplicate_notification() -> None:
    item = Notification(
        "student-1", "application-1:submitted", "Application received", "/applications/1"
    )
    assert deduplicate([item, item]) == [item]


def test_notification_rejects_external_or_protocol_relative_links() -> None:
    assert safe_deep_link("/applications/1") == "/applications/1"
    with pytest.raises(ValueError):
        safe_deep_link("//evil.example")
