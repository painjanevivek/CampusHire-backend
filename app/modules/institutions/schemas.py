from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.auth import UserRole

InvitationStatus = Literal["pending", "expired", "accepted", "revoked"]


class MembershipCreate(BaseModel):
    user_id: UUID
    role: UserRole = UserRole.STUDENT
    reason: str = Field(min_length=10, max_length=500)


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution_id: UUID
    user_id: UUID
    role: str
    status: str
    email: EmailStr | None = None
    username: str | None = None


class MembershipPage(BaseModel):
    items: list[MembershipResponse]
    page: int
    page_size: int
    total: int


class StaffAccountCreate(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
    password: str = Field(min_length=12, max_length=128)
    role: Literal["tnp_admin", "tnp_reviewer", "tnp_auditor"]
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().casefold()

    @field_validator("password")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError("Password cannot contain control characters")
        return value


class StaffAccountResponse(MembershipResponse):
    requires_terms_acceptance: bool


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
    reason: str = Field(min_length=10, max_length=500)


class RosterRowResponse(BaseModel):
    row_number: int
    email: str | None
    enrollment_id: str | None
    full_name: str | None
    status: str
    errors: list[str]


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


class InvitationSummary(BaseModel):
    id: UUID
    email: EmailStr
    enrollment_id: str | None
    full_name: str | None
    role: str
    status: InvitationStatus
    expires_at: datetime
    resend_count: int
    created_at: datetime


class InvitationActionResponse(BaseModel):
    id: UUID
    status: InvitationStatus
    expires_at: datetime
    message: str


class InvitationRevocationRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
