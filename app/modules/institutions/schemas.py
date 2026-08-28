from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.auth import UserRole


class MembershipCreate(BaseModel):
    user_id: UUID
    role: UserRole = UserRole.STUDENT


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution_id: UUID
    user_id: UUID
    role: str
    status: str
    email: EmailStr | None = None


class InstitutionProvisionRequest(BaseModel):
    institution_code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
    institution_name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr


class InstitutionProvisionResponse(BaseModel):
    institution_id: UUID
    admin_invitation_id: UUID
    admin_invitation_token: str
    expires_at: datetime


class MembershipStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(active|suspended|revoked|graduated)$")
    reason: str = Field(min_length=3, max_length=500)


class RosterRowResponse(BaseModel):
    row_number: int
    email: str | None
    enrollment_id: str | None
    full_name: str | None
    status: str
    errors: list[str]
    activation_token: str | None = None


class RosterImportResponse(BaseModel):
    id: UUID
    status: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    invited_rows: int
    committed_at: datetime | None
    rows: list[RosterRowResponse]


class RosterImportSummary(BaseModel):
    id: UUID
    filename: str
    status: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    invited_rows: int
    committed_at: datetime | None
    created_at: datetime
