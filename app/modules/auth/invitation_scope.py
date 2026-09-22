from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import (
    Institution,
    InstitutionDomain,
    MembershipInvitation,
    RosterImport,
    RosterImportRow,
)


async def is_approved_student_invitation(
    db: AsyncSession, invitation: MembershipInvitation
) -> bool:
    """Require a committed institutional roster and a verified college domain."""
    domain = invitation.email.rpartition("@")[2].casefold()
    linked_row = await db.scalar(
        select(RosterImportRow.id)
        .join(RosterImport, RosterImport.id == RosterImportRow.roster_import_id)
        .join(Institution, Institution.id == RosterImport.institution_id)
        .join(InstitutionDomain, InstitutionDomain.institution_id == Institution.id)
        .where(
            RosterImportRow.invitation_id == invitation.id,
            RosterImportRow.email == invitation.email,
            RosterImportRow.status == "invited",
            RosterImport.status == "committed",
            RosterImport.institution_id == invitation.institution_id,
            Institution.is_active.is_(True),
            InstitutionDomain.domain == domain,
            InstitutionDomain.verification_status == "verified",
        )
        .limit(1)
    )
    return linked_row is not None
