import hashlib
import html
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.communications import (
    CommunicationPreference,
    EmailDelivery,
    ProductEvent,
    SupportRequest,
)
from app.modules.auth.security import decrypt_sensitive_payload, encrypt_sensitive_payload
from app.modules.communications.schemas import (
    CommunicationPreferencesResponse,
    CommunicationPreferencesUpdate,
    EmailDeliveryPage,
    EmailDeliveryResponse,
    FunnelMetric,
    FunnelResponse,
    SupportRequestCreate,
    SupportRequestResponse,
)

PRODUCT_EVENTS = frozenset(
    {
        "invitation_accepted",
        "onboarding_step_completed",
        "profile_completed",
        "first_opportunity_viewed",
        "first_application_submitted",
        "resume_completed",
        "roadmap_selected",
        "roster_import_committed",
        "role_published",
        "operation_error",
        "operation_retried",
        "support_requested",
    }
)

_TEMPLATES: dict[str, tuple[str, str, frozenset[str]]] = {
    "invitation": (
        "Activate your CampusHire account",
        "{institution_name} invited you to CampusHire. Activate your account: {activation_url}",
        frozenset({"institution_name", "activation_url"}),
    ),
    "password_reset": (
        "Reset your CampusHire password",
        "A password reset was requested. Continue using this single-use link: {reset_url}",
        frozenset({"reset_url"}),
    ),
    "security_notice": (
        "CampusHire security notice",
        "{message}",
        frozenset({"message"}),
    ),
    "application_status": (
        "Application update: {role_title}",
        "Your application is now {status}. {message} Review the record: {application_url}",
        frozenset({"role_title", "status", "message", "application_url"}),
    ),
    "deadline_reminder": (
        "Application deadline reminder: {role_title}",
        "The deadline is {deadline}. Review the opportunity: {application_url}",
        frozenset({"role_title", "deadline", "application_url"}),
    ),
}


class EmailProvider(Protocol):
    def deliver(self, recipient: str, subject: str, text_body: str) -> str: ...


class OciSmtpEmailProvider:
    """OCI Email Delivery adapter using its authenticated SMTP submission endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def deliver(self, recipient: str, subject: str, text_body: str) -> str:
        settings = self.settings
        if not settings.email_smtp_host or not settings.email_smtp_username:
            raise RuntimeError("email_provider_unavailable")
        if not settings.email_smtp_password:
            raise RuntimeError("email_provider_unavailable")
        message = EmailMessage()
        message["From"] = settings.email_from_address
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(text_body)
        with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(settings.email_smtp_username, settings.email_smtp_password)
            smtp.send_message(message)
        return message["Message-ID"] or f"smtp-{datetime.now(UTC).timestamp():.0f}"


def render_email(template_key: str, variables: dict[str, Any]) -> tuple[str, str]:
    template = _TEMPLATES.get(template_key)
    if template is None:
        raise ValueError("email_template_unknown")
    subject_template, body_template, allowed = template
    if set(variables) != set(allowed):
        raise ValueError("email_template_variables_invalid")
    safe = {key: html.escape(str(value), quote=True)[:1000] for key, value in variables.items()}
    return subject_template.format(**safe), body_template.format(**safe)


def _priority(category: str) -> int:
    return {"security": 0, "account": 5, "application": 15, "reminder": 30}.get(
        category, 20
    )


async def enqueue_email(
    db: AsyncSession,
    *,
    institution_id: UUID | None,
    recipient_email: str,
    category: str,
    template_key: str,
    variables: dict[str, Any],
    dedupe_key: str,
    optional_enabled: bool = True,
) -> EmailDelivery:
    render_email(template_key, variables)
    existing = await db.scalar(select(EmailDelivery).where(EmailDelivery.dedupe_key == dedupe_key))
    if existing:
        return existing
    settings = get_settings()
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    sent_this_month = (
        await db.scalar(
            select(func.count())
            .select_from(EmailDelivery)
            .where(EmailDelivery.sent_at >= month_start)
        )
        or 0
    )
    suppress_optional = category in {"application", "reminder"} and not optional_enabled
    if category == "reminder":
        suppress_optional = suppress_optional or sent_this_month >= int(
            settings.email_monthly_quota * settings.email_optional_suppression_ratio
        )
    stored_variables: dict[str, Any] = variables
    if template_key in {"invitation", "password_reset"}:
        stored_variables = {
            "encrypted": encrypt_sensitive_payload(variables, f"campushire-email:{template_key}")
        }
    item = EmailDelivery(
        institution_id=institution_id,
        recipient_email=recipient_email.strip().casefold(),
        category=category,
        template_key=template_key,
        template_variables=stored_variables,
        dedupe_key=dedupe_key,
        priority=_priority(category),
        status="suppressed" if suppress_optional else "queued",
        max_attempts=settings.email_delivery_max_attempts,
        safe_error_code="optional_email_suppressed" if suppress_optional else None,
    )
    try:
        async with db.begin_nested():
            db.add(item)
            await db.flush()
    except IntegrityError:
        duplicate = await db.scalar(
            select(EmailDelivery).where(EmailDelivery.dedupe_key == dedupe_key)
        )
        if duplicate is None:  # pragma: no cover - defensive database race
            raise
        return duplicate
    return item


async def process_next_email(db: AsyncSession, provider: EmailProvider) -> UUID | None:
    now = datetime.now(UTC)
    item = await db.scalar(
        select(EmailDelivery)
        .where(
            EmailDelivery.status.in_(["queued", "retrying"]),
            EmailDelivery.next_attempt_at <= now,
        )
        .order_by(EmailDelivery.priority, EmailDelivery.created_at)
        .with_for_update(skip_locked=True)
    )
    if item is None:
        return None
    item.status = "sending"
    item.attempts += 1
    await db.flush()
    try:
        variables = dict(item.template_variables)
        if item.template_key in {"invitation", "password_reset"}:
            encrypted = variables.get("encrypted")
            if not isinstance(encrypted, str):
                raise ValueError("sensitive_email_payload_unavailable")
            variables = decrypt_sensitive_payload(
                encrypted, f"campushire-email:{item.template_key}"
            )
        subject, body = render_email(item.template_key, variables)
        item.provider_message_id = provider.deliver(item.recipient_email, subject, body)[:200]
        item.status = "sent"
        item.sent_at = now
        item.safe_error_code = None
        item.template_variables = {}
    except Exception:
        item.safe_error_code = "email_delivery_failed"
        if item.attempts >= item.max_attempts:
            item.status = "failed"
            item.failed_at = now
            if item.template_key in {"invitation", "password_reset"}:
                item.template_variables = {}
        else:
            item.status = "retrying"
            item.next_attempt_at = now + timedelta(seconds=min(2**item.attempts * 30, 3600))
    await db.commit()
    return item.id


async def retry_email(db: AsyncSession, institution_id: UUID, delivery_id: UUID) -> EmailDelivery:
    item = await db.scalar(
        select(EmailDelivery).where(
            EmailDelivery.id == delivery_id,
            EmailDelivery.institution_id == institution_id,
        )
    )
    if item is None:
        raise ValueError("email_delivery_not_found")
    if item.status not in {"failed", "retrying"}:
        raise ValueError("email_delivery_not_retryable")
    item.status = "queued"
    item.attempts = 0
    item.failed_at = None
    item.next_attempt_at = datetime.now(UTC)
    item.safe_error_code = None
    await db.flush()
    return item


def delivery_response(item: EmailDelivery) -> EmailDeliveryResponse:
    return EmailDeliveryResponse.model_validate(item, from_attributes=True)


async def list_email_deliveries(
    db: AsyncSession, institution_id: UUID, status: str | None, limit: int
) -> EmailDeliveryPage:
    query = select(EmailDelivery).where(EmailDelivery.institution_id == institution_id)
    count = select(func.count()).select_from(EmailDelivery).where(
        EmailDelivery.institution_id == institution_id
    )
    if status:
        query = query.where(EmailDelivery.status == status)
        count = count.where(EmailDelivery.status == status)
    items = (await db.scalars(query.order_by(EmailDelivery.created_at.desc()).limit(limit))).all()
    return EmailDeliveryPage(
        items=[delivery_response(item) for item in items], total=(await db.scalar(count)) or 0
    )


async def get_preferences(
    db: AsyncSession, institution_id: UUID, user_id: UUID
) -> CommunicationPreference:
    item = await db.scalar(
        select(CommunicationPreference).where(CommunicationPreference.user_id == user_id)
    )
    if item is None:
        item = CommunicationPreference(user_id=user_id, institution_id=institution_id)
        db.add(item)
        await db.flush()
    return item


async def update_preferences(
    db: AsyncSession,
    institution_id: UUID,
    user_id: UUID,
    payload: CommunicationPreferencesUpdate,
) -> CommunicationPreferencesResponse:
    item = await get_preferences(db, institution_id, user_id)
    item.application_updates = payload.application_updates
    item.deadline_reminders = payload.deadline_reminders
    await db.commit()
    return CommunicationPreferencesResponse(
        application_updates=item.application_updates,
        deadline_reminders=item.deadline_reminders,
    )


def preference_response(item: CommunicationPreference) -> CommunicationPreferencesResponse:
    return CommunicationPreferencesResponse(
        application_updates=item.application_updates,
        deadline_reminders=item.deadline_reminders,
    )


async def record_product_event(
    db: AsyncSession,
    *,
    event_name: str,
    route_group: str,
    institution_id: UUID | None,
    dedupe_key: str | None = None,
) -> ProductEvent:
    if event_name not in PRODUCT_EVENTS:
        raise ValueError("product_event_not_allowed")
    safe_dedupe_key = hashlib.sha256(dedupe_key.encode()).hexdigest() if dedupe_key else None
    if safe_dedupe_key:
        existing = await db.scalar(
            select(ProductEvent).where(ProductEvent.dedupe_key == safe_dedupe_key)
        )
        if existing:
            return existing
    event = ProductEvent(
        institution_id=institution_id,
        event_name=event_name,
        route_group=route_group,
        dedupe_key=safe_dedupe_key,
    )
    db.add(event)
    return event


async def record_bounce(db: AsyncSession, provider_message_id: str) -> EmailDelivery:
    item = await db.scalar(
        select(EmailDelivery).where(EmailDelivery.provider_message_id == provider_message_id)
    )
    if item is None:
        raise ValueError("email_delivery_not_found")
    item.status = "bounced"
    item.bounced_at = datetime.now(UTC)
    item.safe_error_code = "email_delivery_bounced"
    await db.commit()
    return item


async def funnel_metrics(
    db: AsyncSession, institution_id: UUID, window_days: int
) -> FunnelResponse:
    start = datetime.now(UTC) - timedelta(days=window_days)
    rows = (
        await db.execute(
            select(ProductEvent.event_name, func.count())
            .where(
                ProductEvent.institution_id == institution_id,
                ProductEvent.occurred_at >= start,
            )
            .group_by(ProductEvent.event_name)
            .order_by(ProductEvent.event_name)
        )
    ).all()
    return FunnelResponse(
        metrics=[FunnelMetric(event_name=name, count=count) for name, count in rows],
        window_days=window_days,
    )


async def create_support_request(
    db: AsyncSession,
    institution_id: UUID | None,
    payload: SupportRequestCreate,
) -> SupportRequestResponse:
    item = SupportRequest(institution_id=institution_id, **payload.model_dump())
    db.add(item)
    await db.flush()
    await record_product_event(
        db,
        event_name="support_requested",
        route_group=payload.route_context,
        institution_id=institution_id,
        dedupe_key=f"support:{item.id}",
    )
    await db.commit()
    return SupportRequestResponse(reference=item.id, status=item.status, created_at=item.created_at)
