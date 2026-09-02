import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.auth import InstitutionMembership, MembershipStatus, User, UserRole
from app.models.communications import CommunicationPreference
from app.models.recruitment import (
    Application,
    PlacementDrive,
    PlacementRole,
    PublicationStatus,
    SavedOpportunity,
)
from app.modules.communications.service import enqueue_email


def _reminder_dedupe_key(saved_id: object, deadline: datetime) -> str:
    identity = f"{saved_id}:{deadline.isoformat()}".encode()
    return f"deadline-reminder:{hashlib.sha256(identity).hexdigest()}"


async def enqueue_upcoming_deadline_reminders(
    db: AsyncSession,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> int:
    """Queue one privacy-minimized reminder for each saved, unapplied-to role."""

    active_settings = settings or get_settings()
    current_time = now or datetime.now(UTC)
    cutoff = current_time + timedelta(hours=active_settings.email_deadline_reminder_hours)
    rows = (
        await db.execute(
            select(
                SavedOpportunity,
                User.email,
                PlacementRole.title,
                PlacementDrive.deadline_at,
                CommunicationPreference.deadline_reminders,
            )
            .join(User, User.id == SavedOpportunity.student_user_id)
            .join(PlacementRole, PlacementRole.id == SavedOpportunity.role_id)
            .join(PlacementDrive, PlacementDrive.id == PlacementRole.drive_id)
            .join(
                InstitutionMembership,
                and_(
                    InstitutionMembership.institution_id == SavedOpportunity.institution_id,
                    InstitutionMembership.user_id == SavedOpportunity.student_user_id,
                ),
            )
            .outerjoin(
                CommunicationPreference,
                CommunicationPreference.user_id == SavedOpportunity.student_user_id,
            )
            .outerjoin(
                Application,
                and_(
                    Application.student_user_id == SavedOpportunity.student_user_id,
                    Application.role_id == SavedOpportunity.role_id,
                ),
            )
            .where(
                User.is_active.is_(True),
                InstitutionMembership.role == UserRole.STUDENT.value,
                InstitutionMembership.status == MembershipStatus.ACTIVE.value,
                PlacementRole.status == PublicationStatus.PUBLISHED.value,
                PlacementDrive.status == PublicationStatus.PUBLISHED.value,
                PlacementDrive.deadline_at > current_time,
                PlacementDrive.deadline_at <= cutoff,
                Application.id.is_(None),
            )
            .order_by(PlacementDrive.deadline_at, SavedOpportunity.id)
            .limit(active_settings.email_reminder_batch_size)
        )
    ).all()

    queued = 0
    frontend = str(active_settings.frontend_origins[0]).rstrip("/")
    for saved, recipient, role_title, deadline, preference in rows:
        delivery = await enqueue_email(
            db,
            institution_id=saved.institution_id,
            recipient_email=recipient,
            category="reminder",
            template_key="deadline_reminder",
            variables={
                "role_title": role_title,
                "deadline": deadline.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC"),
                "application_url": f"{frontend}/opportunities/{saved.role_id}",
            },
            dedupe_key=_reminder_dedupe_key(saved.id, deadline),
            optional_enabled=preference is not False,
        )
        if delivery.status == "queued":
            queued += 1
    return queued
