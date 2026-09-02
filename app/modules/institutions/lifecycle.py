import csv
import hashlib
import io
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.auth import (
    Institution,
    MembershipInvitation,
    RosterImport,
    RosterImportRow,
    User,
    UserRole,
)
from app.modules.audit.service import record_audit_event
from app.modules.auth.security import hash_secret, new_secret, normalize_email
from app.modules.communications.service import enqueue_email, record_product_event

email_adapter = TypeAdapter(EmailStr)


class ProvisionConflictError(Exception):
    pass


class InvalidRosterError(Exception):
    pass


@dataclass(frozen=True)
class ProvisionedInstitution:
    institution: Institution
    invitation: MembershipInvitation
    raw_token: str


async def provision_institution(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    admin_email: str,
    correlation_id: str | None,
) -> ProvisionedInstitution:
    normalized_email = normalize_email(admin_email)
    conflict = await db.scalar(
        select(Institution.id).where(Institution.code == code)
    ) or await db.scalar(select(User.id).where(User.email == normalized_email))
    if conflict is not None:
        raise ProvisionConflictError
    institution = Institution(code=code, name=name)
    db.add(institution)
    await db.flush()
    raw_token = new_secret()
    invitation = MembershipInvitation(
        institution_id=institution.id,
        email=normalized_email,
        role=UserRole.TNP_OWNER.value,
        token_hash=hash_secret(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=get_settings().invitation_ttl_hours),
    )
    db.add(invitation)
    await db.flush()
    record_audit_event(
        db,
        institution_id=institution.id,
        event_type="institution.provisioned",
        resource_type="institution",
        resource_id=str(institution.id),
        correlation_id=correlation_id,
        details={"admin_invitation_id": str(invitation.id)},
    )
    await db.commit()
    return ProvisionedInstitution(institution, invitation, raw_token)


def _safe_cell(value: str | None, maximum: int) -> str:
    normalized = unicodedata.normalize("NFC", (value or "").strip())
    if len(normalized) > maximum:
        raise ValueError("value_too_long")
    if normalized.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        raise ValueError("spreadsheet_formula")
    if "\x00" in normalized:
        raise ValueError("invalid_character")
    return normalized


async def preview_roster(
    db: AsyncSession,
    *,
    institution_id: UUID,
    actor_user_id: UUID,
    filename: str,
    content: bytes,
    correlation_id: str | None,
) -> RosterImport:
    if not content or len(content) > get_settings().roster_max_bytes:
        raise InvalidRosterError("The roster file is empty or exceeds the upload limit.")
    digest = hashlib.sha256(content).hexdigest()
    existing = await db.scalar(
        select(RosterImport).where(
            RosterImport.institution_id == institution_id,
            RosterImport.content_sha256 == digest,
        )
    )
    if existing is not None:
        return existing
    try:
        decoded = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise InvalidRosterError("The roster must be valid UTF-8 text.") from error
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    required = {"email", "enrollment_id", "full_name"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise InvalidRosterError("The roster must include email, enrollment_id, and full_name.")
    roster = RosterImport(
        institution_id=institution_id,
        created_by_user_id=actor_user_id,
        filename=filename[:200] or "roster.csv",
        content_sha256=digest,
    )
    db.add(roster)
    await db.flush()
    seen_emails: set[str] = set()
    seen_enrollments: set[str] = set()
    rows: list[RosterImportRow] = []
    for row_number, source in enumerate(reader, start=2):
        if row_number > 5_001:
            raise InvalidRosterError("A roster may contain at most 5,000 rows.")
        errors: list[str] = []
        email: str | None
        enrollment_id: str | None
        full_name: str | None
        try:
            email = normalize_email(_safe_cell(source.get("email"), 320))
            email = str(email_adapter.validate_python(email))
        except (ValueError, ValidationError):
            email = normalize_email(source.get("email") or "")[:320] or None
            errors.append("invalid_email")
        try:
            enrollment_id = _safe_cell(source.get("enrollment_id"), 100)
            if not enrollment_id:
                errors.append("missing_enrollment_id")
        except ValueError as error:
            enrollment_id = (source.get("enrollment_id") or "")[:100] or None
            errors.append(str(error))
        try:
            full_name = _safe_cell(source.get("full_name"), 200)
            if not full_name:
                errors.append("missing_full_name")
        except ValueError as error:
            full_name = (source.get("full_name") or "")[:200] or None
            errors.append(str(error))
        if email and email in seen_emails:
            errors.append("duplicate_email")
        if enrollment_id and enrollment_id in seen_enrollments:
            errors.append("duplicate_enrollment_id")
        if email:
            seen_emails.add(email)
        if enrollment_id:
            seen_enrollments.add(enrollment_id)
        rows.append(
            RosterImportRow(
                roster_import_id=roster.id,
                row_number=row_number,
                email=email,
                enrollment_id=enrollment_id,
                full_name=full_name,
                status="invalid" if errors else "valid",
                errors=errors,
            )
        )
    if not rows:
        raise InvalidRosterError("The roster does not contain any student rows.")
    roster.total_rows = len(rows)
    roster.valid_rows = sum(item.status == "valid" for item in rows)
    roster.invalid_rows = roster.total_rows - roster.valid_rows
    db.add_all(rows)
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="roster.previewed",
        resource_type="roster_import",
        resource_id=str(roster.id),
        correlation_id=correlation_id,
        details={
            "total_rows": roster.total_rows,
            "valid_rows": roster.valid_rows,
            "invalid_rows": roster.invalid_rows,
        },
    )
    await db.commit()
    await db.refresh(roster)
    return roster


async def get_roster_import(
    db: AsyncSession,
    institution_id: UUID,
    roster_import_id: UUID,
    *,
    for_update: bool = False,
) -> tuple[RosterImport | None, list[RosterImportRow]]:
    roster_query = select(RosterImport).where(
        RosterImport.id == roster_import_id,
        RosterImport.institution_id == institution_id,
    )
    if for_update:
        roster_query = roster_query.with_for_update()
    roster = await db.scalar(roster_query)
    if roster is None:
        return None, []
    records = await db.scalars(
        select(RosterImportRow)
        .where(RosterImportRow.roster_import_id == roster.id)
        .order_by(RosterImportRow.row_number)
    )
    return roster, list(records.all())


async def commit_roster(
    db: AsyncSession,
    *,
    institution_id: UUID,
    roster_import_id: UUID,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> tuple[RosterImport | None, dict[UUID, str]]:
    institution = await db.scalar(
        select(Institution).where(Institution.id == institution_id).with_for_update()
    )
    if institution is None:
        return None, {}
    roster, rows = await get_roster_import(
        db, institution_id, roster_import_id, for_update=True
    )
    if roster is None:
        return None, {}
    if roster.status == "committed":
        return roster, {}
    tokens: dict[UUID, str] = {}
    institution_name = institution.name
    frontend = str(get_settings().frontend_origins[0]).rstrip("/")
    for row in rows:
        if row.status != "valid" or row.email is None:
            continue
        existing_user = await db.scalar(select(User.id).where(User.email == row.email))
        existing_invitation = await db.scalar(
            select(MembershipInvitation.id).where(
                MembershipInvitation.institution_id == institution_id,
                MembershipInvitation.revoked_at.is_(None),
                or_(
                    MembershipInvitation.email == row.email,
                    MembershipInvitation.enrollment_id == row.enrollment_id,
                ),
            )
        )
        if existing_user is not None or existing_invitation is not None:
            row.status = "duplicate"
            row.errors = ["account_or_invitation_exists"]
            continue
        raw_token = new_secret()
        invitation = MembershipInvitation(
            institution_id=institution_id,
            email=row.email,
            enrollment_id=row.enrollment_id,
            full_name=row.full_name,
            role=UserRole.STUDENT.value,
            token_hash=hash_secret(raw_token),
            expires_at=datetime.now(UTC) + timedelta(hours=get_settings().invitation_ttl_hours),
            created_by_user_id=actor_user_id,
        )
        db.add(invitation)
        await db.flush()
        row.status = "invited"
        row.invitation_id = invitation.id
        tokens[row.id] = raw_token
        await enqueue_email(
            db,
            institution_id=institution_id,
            recipient_email=row.email,
            category="account",
            template_key="invitation",
            variables={
                "institution_name": institution_name,
                "activation_url": f"{frontend}/activate/{raw_token}",
            },
            dedupe_key=f"invitation:{invitation.id}",
        )
    roster.status = "committed"
    roster.invited_rows = sum(item.status == "invited" for item in rows)
    roster.committed_at = datetime.now(UTC)
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="roster.committed",
        resource_type="roster_import",
        resource_id=str(roster.id),
        correlation_id=correlation_id,
        details={"invited_rows": roster.invited_rows},
    )
    await record_product_event(
        db,
        event_name="roster_import_committed",
        route_group="admin_students",
        institution_id=institution_id,
        dedupe_key=f"roster-import:{roster.id}",
    )
    await db.commit()
    return roster, tokens


def invitation_status(
    invitation: MembershipInvitation, *, now: datetime | None = None
) -> Literal["pending", "expired", "accepted", "revoked"]:
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.accepted_at is not None:
        return "accepted"
    current = now or datetime.now(UTC)
    expires_at = (
        invitation.expires_at
        if invitation.expires_at.tzinfo
        else invitation.expires_at.replace(tzinfo=UTC)
    )
    return "expired" if expires_at <= current else "pending"


async def list_invitations(
    db: AsyncSession, *, institution_id: UUID, limit: int = 100
) -> list[MembershipInvitation]:
    records = await db.scalars(
        select(MembershipInvitation)
        .where(MembershipInvitation.institution_id == institution_id)
        .order_by(MembershipInvitation.created_at.desc(), MembershipInvitation.id)
        .limit(limit)
    )
    return list(records.all())


async def resend_invitation(
    db: AsyncSession,
    *,
    institution_id: UUID,
    invitation_id: UUID,
    actor_user_id: UUID,
    correlation_id: str | None,
) -> tuple[MembershipInvitation | None, str | None]:
    invitation = await db.scalar(
        select(MembershipInvitation)
        .where(
            MembershipInvitation.id == invitation_id,
            MembershipInvitation.institution_id == institution_id,
            MembershipInvitation.accepted_at.is_(None),
            MembershipInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if invitation is None:
        return None, None
    raw_token = new_secret()
    invitation.token_hash = hash_secret(raw_token)
    invitation.expires_at = datetime.now(UTC) + timedelta(hours=get_settings().invitation_ttl_hours)
    invitation.resend_count += 1
    institution = await db.get(Institution, institution_id)
    if institution is None:  # pragma: no cover - foreign key guarantees this
        return None, None
    await enqueue_email(
        db,
        institution_id=institution_id,
        recipient_email=invitation.email,
        category="account",
        template_key="invitation",
        variables={
            "institution_name": institution.name,
            "activation_url": (
                f"{str(get_settings().frontend_origins[0]).rstrip('/')}/activate/{raw_token}"
            ),
        },
        dedupe_key=f"invitation-resend:{invitation.id}:{invitation.resend_count}",
    )
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="invitation.resent",
        resource_type="membership_invitation",
        resource_id=str(invitation.id),
        correlation_id=correlation_id,
    )
    await db.commit()
    return invitation, raw_token


async def revoke_invitation(
    db: AsyncSession,
    *,
    institution_id: UUID,
    invitation_id: UUID,
    actor_user_id: UUID,
    reason: str,
    correlation_id: str | None,
) -> MembershipInvitation | None:
    invitation = await db.scalar(
        select(MembershipInvitation)
        .where(
            MembershipInvitation.id == invitation_id,
            MembershipInvitation.institution_id == institution_id,
            MembershipInvitation.accepted_at.is_(None),
            MembershipInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if invitation is None:
        return None
    invitation.revoked_at = datetime.now(UTC)
    record_audit_event(
        db,
        actor_user_id=actor_user_id,
        institution_id=institution_id,
        event_type="invitation.revoked",
        resource_type="membership_invitation",
        resource_id=str(invitation.id),
        correlation_id=correlation_id,
        reason=reason,
    )
    await db.commit()
    return invitation
