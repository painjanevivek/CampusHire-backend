from fastapi import APIRouter, Depends, HTTPException, status

from app.models.auth import UserRole
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.profiles.schemas import (
    EducationUpdate,
    IdentityUpdate,
    LinksUpdate,
    PreferencesUpdate,
    ProfileResponse,
    ProfileUpdate,
    SkillsUpdate,
)
from app.modules.profiles.service import (
    ProfileConflictError,
    get_or_create,
    to_response,
    update_profile,
)

router = APIRouter(
    prefix="/profile", dependencies=[Depends(require_roles(UserRole.STUDENT.value))]
)
ProfilePayload = (
    ProfileUpdate
    | IdentityUpdate
    | EducationUpdate
    | SkillsUpdate
    | PreferencesUpdate
    | LinksUpdate
)


@router.get("", response_model=ProfileResponse)
async def read_profile(db: Database, principal: CurrentPrincipal) -> ProfileResponse:
    return to_response(await get_or_create(db, principal.user, principal.institution_id))


async def _update(
    payload: ProfilePayload, db: Database, principal: CurrentPrincipal
) -> ProfileResponse:
    try:
        profile = await update_profile(
            db, principal.user, payload, institution_id=principal.institution_id
        )
    except ProfileConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "profile_revision_conflict",
                "message": "The profile changed in another session.",
                "current_revision": error.current_revision,
            },
        ) from error
    return to_response(profile)


@router.patch(
    "", response_model=ProfileResponse, dependencies=[Depends(verify_authenticated_csrf)]
)
async def patch_profile(
    payload: ProfileUpdate, db: Database, principal: CurrentPrincipal
) -> ProfileResponse:
    return await _update(payload, db, principal)


@router.patch(
    "/identity", response_model=ProfileResponse, dependencies=[Depends(verify_authenticated_csrf)]
)
async def patch_identity(
    payload: IdentityUpdate, db: Database, principal: CurrentPrincipal
) -> ProfileResponse:
    return await _update(payload, db, principal)


@router.put(
    "/education", response_model=ProfileResponse, dependencies=[Depends(verify_authenticated_csrf)]
)
async def replace_education(
    payload: EducationUpdate, db: Database, principal: CurrentPrincipal
) -> ProfileResponse:
    return await _update(payload, db, principal)


@router.put(
    "/skills", response_model=ProfileResponse, dependencies=[Depends(verify_authenticated_csrf)]
)
async def replace_skills(
    payload: SkillsUpdate, db: Database, principal: CurrentPrincipal
) -> ProfileResponse:
    return await _update(payload, db, principal)


@router.put(
    "/preferences",
    response_model=ProfileResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def replace_preferences(
    payload: PreferencesUpdate, db: Database, principal: CurrentPrincipal
) -> ProfileResponse:
    return await _update(payload, db, principal)


@router.put(
    "/links", response_model=ProfileResponse, dependencies=[Depends(verify_authenticated_csrf)]
)
async def replace_links(
    payload: LinksUpdate, db: Database, principal: CurrentPrincipal
) -> ProfileResponse:
    return await _update(payload, db, principal)
