from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


def _reject_password_control_characters(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise ValueError("Password cannot contain control characters")
    return value


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    surname: str = Field(min_length=1, max_length=100)
    dob: date
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    re_enter_password: str = Field(min_length=12, max_length=128)
    terms_version: str = Field(min_length=1, max_length=64)
    privacy_version: str = Field(min_length=1, max_length=64)
    invitation_code: str | None = Field(default=None, min_length=20, max_length=200)

    @field_validator("name", "surname")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Name cannot be blank")
        return normalized

    @field_validator("password", "re_enter_password")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        return _reject_password_control_characters(value)

    @model_validator(mode="after")
    def passwords_match(self) -> "SignupRequest":
        if self.password != self.re_enter_password:
            raise ValueError("Passwords do not match")
        return self


class RegistrationStartResponse(BaseModel):
    status: Literal["registered", "registration_unavailable"]
    message: str
    next_path: str | None = None


class InstitutionRegistrationRequestCreate(BaseModel):
    institution_name: str = Field(min_length=2, max_length=200)
    institution_code: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$")
    institutional_email: EmailStr
    domain: str = Field(
        min_length=3,
        max_length=255,
        pattern=r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    )

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return value.strip().casefold().removeprefix("www.")


class InstitutionRegistrationStartResponse(BaseModel):
    request_id: UUID
    status: Literal["verification_pending"]
    message: str


class RegistrationTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class InstitutionRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    institution_name: str
    institution_code: str
    domain: str
    admin_email: EmailStr
    status: str
    duplicate_detected: bool
    email_verified_at: datetime | None
    reviewed_at: datetime | None
    institution_id: UUID | None
    created_at: datetime


class InstitutionRegistrationDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def require_rejection_reason(cls, value: str | None, info: object) -> str | None:
        del info
        return value.strip() if value else None


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
    student_signup_ready: bool = False


class InvitationAcceptRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)
    terms_version: str = Field(min_length=1, max_length=64)
    privacy_version: str = Field(min_length=1, max_length=64)

    @field_validator("password")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        return _reject_password_control_characters(value)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        return _reject_password_control_characters(value)


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
