from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.models import Base
from app.models.auth import (
    Institution,
    InstitutionMembership,
    MembershipStatus,
    PasswordResetToken,
    User,
    UserRole,
)
from app.models.communications import CommunicationPreference, EmailDelivery, ProductEvent
from app.models.recruitment import (
    Application,
    Company,
    PlacementDrive,
    PlacementRole,
    PublicationStatus,
    SavedOpportunity,
)
from app.modules.auth.security import hash_secret
from app.modules.auth.service import confirm_password_reset
from app.modules.communications.reminders import enqueue_upcoming_deadline_reminders
from app.modules.communications.schemas import SupportRequestCreate
from app.modules.communications.service import (
    enqueue_email,
    process_next_email,
    record_product_event,
    render_email,
)
from app.modules.institutions.lifecycle import provision_institution

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
        self.bodies: list[str] = []

    def deliver(self, recipient: str, subject: str, text_body: str) -> str:
        if self.fail:
            raise RuntimeError("provider details must not be persisted")
        self.subjects.append(subject)
        self.bodies.append(text_body)
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
        assert "https://example.test/reset" not in str(stored.template_variables)


async def test_sensitive_outbox_payload_is_encrypted_then_purged_after_delivery() -> None:
    secret_url = "https://example.test/reset?token=raw-capability"  # noqa: S105
    async with Session() as db:
        item = await enqueue_email(
            db,
            institution_id=None,
            recipient_email="student@example.edu",
            category="account",
            template_key="password_reset",
            variables={"reset_url": secret_url},
            dedupe_key="reset-sensitive-1",
        )
        await db.commit()
        assert secret_url not in str(item.template_variables)

    provider = RecordingProvider()
    async with Session() as db:
        assert await process_next_email(db, provider) == item.id
        stored = await db.get(EmailDelivery, item.id)
        assert stored is not None and stored.template_variables == {}
    assert secret_url in provider.bodies[0]


def test_smtp_starttls_uses_a_verifying_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from ssl import CERT_REQUIRED
    from types import SimpleNamespace

    from app.modules.communications import service

    captured: dict[str, object] = {}

    class FakeSmtp:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def __enter__(self) -> "FakeSmtp":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def starttls(self, *, context: object) -> None:
            captured["context"] = context

        def login(self, *_: object) -> None:
            return None

        def send_message(self, *_: object) -> None:
            return None

    monkeypatch.setattr(service.smtplib, "SMTP", FakeSmtp)
    settings = SimpleNamespace(
        email_smtp_host="smtp.example.test",
        email_smtp_port=587,
        email_smtp_username="user",
        email_smtp_password="password",  # noqa: S106
        email_from_address="no-reply@example.test",
    )
    service.OciSmtpEmailProvider(settings).deliver("student@example.edu", "Subject", "Body")  # type: ignore[arg-type]
    context = captured["context"]
    assert context.check_hostname is True  # type: ignore[union-attr]
    assert context.verify_mode == CERT_REQUIRED  # type: ignore[union-attr]


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


async def test_provisioning_and_password_change_queue_account_security_email() -> None:
    async with Session() as db:
        provisioned = await provision_institution(
            db,
            code="COMM-C",
            name="Account Communications Institute",
            admin_email="owner@example.edu",
            correlation_id="test-correlation",
        )
        invitation = await db.scalar(
            select(EmailDelivery).where(EmailDelivery.template_key == "invitation")
        )
        assert invitation is not None
        assert provisioned.raw_token not in str(invitation.template_variables)

        user = User(
            institution_id=provisioned.institution.id,
            email="student@example.edu",
            password_hash="previous-password-hash",  # noqa: S106
            role=UserRole.STUDENT.value,
        )
        db.add(user)
        await db.flush()
        raw_token = "single-use-password-reset-token"  # noqa: S105
        reset = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_secret(raw_token),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        db.add(reset)
        await db.commit()

        await confirm_password_reset(
            db,
            raw_token,
            "a replacement campus passphrase",
            "test-correlation",
        )
        security = await db.scalar(
            select(EmailDelivery).where(
                EmailDelivery.template_key == "security_notice",
                EmailDelivery.recipient_email == user.email,
            )
        )
        assert security is not None
        assert security.category == "security"
        assert security.status == "queued"


async def test_deadline_sweep_respects_preferences_and_existing_applications() -> None:
    now = datetime.now(UTC)
    async with Session() as db:
        institution = Institution(code="COMM-D", name="Reminder Institute")
        db.add(institution)
        await db.flush()
        company = Company(
            institution_id=institution.id,
            name="Reminder Company",
            description="Placement roles",
        )
        db.add(company)
        await db.flush()
        drive = PlacementDrive(
            institution_id=institution.id,
            company_id=company.id,
            title="Reminder Drive",
            description="An active placement drive",
            location="Campus",
            work_mode="onsite",
            opens_at=now - timedelta(days=1),
            deadline_at=now + timedelta(hours=6),
            status=PublicationStatus.PUBLISHED.value,
        )
        db.add(drive)
        await db.flush()
        role = PlacementRole(
            institution_id=institution.id,
            drive_id=drive.id,
            title="Graduate Engineer",
            description="Graduate role",
            employment_type="full_time",
            location="Campus",
            work_mode="onsite",
            skills=[],
            requirements=[],
            status=PublicationStatus.PUBLISHED.value,
        )
        db.add(role)
        await db.flush()

        users = [
            User(
                institution_id=institution.id,
                email=f"reminder-{label}@example.edu",
                password_hash="test-password-hash",  # noqa: S106
                role=UserRole.STUDENT.value,
            )
            for label in ("enabled", "disabled", "applied")
        ]
        db.add_all(users)
        await db.flush()
        for user in users:
            db.add(
                InstitutionMembership(
                    institution_id=institution.id,
                    user_id=user.id,
                    role=UserRole.STUDENT.value,
                    status=MembershipStatus.ACTIVE.value,
                )
            )
            db.add(
                SavedOpportunity(
                    institution_id=institution.id,
                    student_user_id=user.id,
                    role_id=role.id,
                    created_at=now,
                )
            )
        db.add(
            CommunicationPreference(
                user_id=users[1].id,
                institution_id=institution.id,
                deadline_reminders=False,
            )
        )
        db.add(
            Application(
                institution_id=institution.id,
                role_id=role.id,
                student_user_id=users[2].id,
                resume_version_id=uuid4(),
                eligibility_evaluation_id=uuid4(),
                idempotency_key="existing-application",
                role_snapshot={},
                resume_snapshot={},
                facts_snapshot={},
                rule_snapshot={},
                eligibility_snapshot={},
            )
        )
        await db.commit()

        queued = await enqueue_upcoming_deadline_reminders(
            db,
            settings=Settings(
                email_deadline_reminder_hours=24,
                email_reminder_batch_size=100,
            ),
            now=now,
        )
        await db.commit()
        deliveries = list(
            (
                await db.scalars(
                    select(EmailDelivery).where(
                        EmailDelivery.template_key == "deadline_reminder"
                    )
                )
            ).all()
        )
        assert queued == 1
        assert {item.status for item in deliveries} == {"queued", "suppressed"}
        assert users[2].email not in {item.recipient_email for item in deliveries}
        assert all(str(user.id) not in item.dedupe_key for item in deliveries for user in users)
