from fastapi import APIRouter, Depends

from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentUser,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.profiles.schemas import ProfileResponse, ProfileUpdate
from app.modules.profiles.service import get_or_create, to_response, update_profile

router = APIRouter(prefix="/profile")
Student = CurrentUser


@router.get(
    "",
    response_model=ProfileResponse,
    dependencies=[Depends(require_roles(UserRole.STUDENT.value))],
)
async def read_profile(db: Database, user: Student) -> ProfileResponse:
    return to_response(await get_or_create(db, user))


@router.patch(
    "",
    response_model=ProfileResponse,
    dependencies=[
        Depends(require_roles(UserRole.STUDENT.value)),
        Depends(verify_authenticated_csrf),
    ],
)
async def patch_profile(payload: ProfileUpdate, db: Database, user: Student) -> ProfileResponse:
    return to_response(await update_profile(db, user, payload))
