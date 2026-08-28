from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class DataDeletionCreate(BaseModel):
    confirmation: Literal["DELETE MY CAMPUSHIRE DATA"]
    scope: Literal["account_all_memberships"]


class DataDeletionResponse(BaseModel):
    id: UUID
    status: str
    requested_at: datetime
    message: str
