from uuid import UUID

from pydantic import BaseModel, ConfigDict

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
