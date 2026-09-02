from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError("Password cannot contain control characters")
        return value


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class DemoSignInRequest(BaseModel):
    role: Literal["student", "tnp_admin"]


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: str
    institution_id: UUID | None = None
    membership_id: UUID | None = None
    membership_status: str | None = None


class SignInResponse(BaseModel):
    user: UserResponse
    next_step: str = "complete"


class InvitationResponse(BaseModel):
    id: UUID
    institution_id: UUID
    email: EmailStr
    role: str
    expires_at: datetime


class InvitationAcceptRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)
    terms_version: str = Field(min_length=1, max_length=64)
    privacy_version: str = Field(min_length=1, max_length=64)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class MfaCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaConfirmResponse(BaseModel):
    recovery_codes: list[str]


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=32)


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    device_summary: str | None
    current: bool
