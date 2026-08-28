from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base
from app.models.auth import Institution
from app.models.communications import EmailDelivery, ProductEvent
from app.modules.communications.schemas import SupportRequestCreate
from app.modules.communications.service import (
    enqueue_email,
    process_next_email,
    record_product_event,
    render_email,
)

engine = create_async_engine(
    "sqlite+aiosqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


class RecordingProvider:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.subjects: list[str] = []

    def deliver(self, recipient: str, subject: str, text_body: str) -> str:
        if self.fail:
            raise RuntimeError("provider details must not be persisted")
        self.subjects.append(subject)
        return f"provider-{len(self.subjects)}"


async def test_queue_deduplicates_prioritizes_and_suppresses_optional_email() -> None:
    async with Session() as db:
        institution = Institution(code="COMM-A", name="Communication Institute")
        db.add(institution)
        await db.flush()
        reminder = await enqueue_email(
            db,
            institution_id=institution.id,
            recipient_email="student@example.edu",
            category="reminder",
            template_key="deadline_reminder",
            variables={
                "role_title": "Engineer",
                "deadline": "Friday",
                "application_url": "https://example.test/opportunities/1",
            },
            dedupe_key="reminder-1",
            optional_enabled=False,
        )
        security = await enqueue_email(
            db,
            institution_id=institution.id,
            recipient_email="student@example.edu",
            category="security",
            template_key="security_notice",
            variables={"message": "A new sign-in was recorded."},
            dedupe_key="security-1",
        )
        duplicate = await enqueue_email(
            db,
            institution_id=institution.id,
            recipient_email="student@example.edu",
            category="security",
            template_key="security_notice",
            variables={"message": "A new sign-in was recorded."},
            dedupe_key="security-1",
        )
        await db.commit()
        assert reminder.status == "suppressed"
        assert duplicate.id == security.id

    provider = RecordingProvider()
    async with Session() as db:
        processed = await process_next_email(db, provider)
        assert processed == security.id
        assert provider.subjects == ["CampusHire security notice"]


async def test_delivery_failure_records_only_a_safe_code() -> None:
    async with Session() as db:
        institution = Institution(code="COMM-B", name="Retry Institute")
        db.add(institution)
        await db.flush()
        item = await enqueue_email(
            db,
            institution_id=institution.id,
            recipient_email="student@example.edu",
            category="account",
            template_key="password_reset",
            variables={"reset_url": "https://example.test/reset"},
            dedupe_key="reset-1",
        )
        await db.commit()
    async with Session() as db:
        await process_next_email(db, RecordingProvider(fail=True))
        stored = await db.get(EmailDelivery, item.id)
        assert stored is not None
        assert stored.status == "retrying"
        assert stored.safe_error_code == "email_delivery_failed"


async def test_product_event_hashes_dedupe_identity_and_is_idempotent() -> None:
    async with Session() as db:
        first = await record_product_event(
            db,
            event_name="profile_completed",
            route_group="profile",
            institution_id=None,
            dedupe_key="profile-completed:user-private-id",
        )
        await db.commit()
        second = await record_product_event(
            db,
            event_name="profile_completed",
            route_group="profile",
            institution_id=None,
            dedupe_key="profile-completed:user-private-id",
        )
        assert second.id == first.id
        stored = await db.scalar(select(ProductEvent).where(ProductEvent.id == first.id))
        assert stored is not None
        assert stored.dedupe_key is not None
        assert "user-private-id" not in stored.dedupe_key


def test_templates_escape_content_and_support_rejects_personal_identifiers() -> None:
    _, body = render_email("security_notice", {"message": "<script>alert(1)</script>"})
    assert "<script>" not in body
    with pytest.raises(ValidationError):
        SupportRequestCreate(
            category="account",
            route_context="/profile",
            message="Please contact student@example.edu about this issue.",
        )
