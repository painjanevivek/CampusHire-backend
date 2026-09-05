from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.rate_limit import enforce_fixed_window_limit
from app.models.auth import User, UserRole
from app.models.profile import ProfilePhoto
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    Database,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.profiles.photo import (
    MAX_PHOTO_BYTES,
    InvalidPhoto,
    ProfilePhotoResponse,
    normalize_photo,
    photo_response,
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

router = APIRouter(prefix="/profile", dependencies=[Depends(require_roles(UserRole.STUDENT.value))])
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
    profile = await get_or_create(db, principal.user, principal.institution_id)
    return to_response(profile, principal.user.email)


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
    return to_response(profile, principal.user.email)


@router.get("/photo", response_model=ProfilePhotoResponse)
async def read_photo(
    db: Database, principal: CurrentPrincipal, response: Response
) -> ProfilePhotoResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return photo_response(await db.get(ProfilePhoto, principal.user.id))


@router.put(
    "/photo", response_model=ProfilePhotoResponse, dependencies=[Depends(verify_authenticated_csrf)]
)
async def upload_photo(
    request: Request,
    file: Annotated[UploadFile, File()],
    db: Database,
    principal: CurrentPrincipal,
    response: Response,
) -> ProfilePhotoResponse:
    try:
        await enforce_fixed_window_limit(
            request,
            namespace="profile-photo",
            identity=str(principal.user.id),
            limit=10,
            unavailable_detail="Photo uploads are temporarily unavailable.",
        )
        data = await file.read(MAX_PHOTO_BYTES + 1)
        image = await run_in_threadpool(
            normalize_photo, data, file.content_type or "", file.filename or ""
        )
    except InvalidPhoto as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()
    # Serialize first upload and replacement without a user-supplied owner identifier.
    await db.scalar(select(User).where(User.id == principal.user.id).with_for_update())
    photo = await db.get(ProfilePhoto, principal.user.id)
    if photo is None:
        photo = ProfilePhoto(user_id=principal.user.id, image=image)
        db.add(photo)
    else:
        photo.image = image
    await db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return photo_response(photo)


@router.delete("/photo", status_code=204, dependencies=[Depends(verify_authenticated_csrf)])
async def remove_photo(db: Database, principal: CurrentPrincipal) -> Response:
    await db.scalar(select(User).where(User.id == principal.user.id).with_for_update())
    photo = await db.get(ProfilePhoto, principal.user.id)
    if photo is not None:
        await db.delete(photo)
        await db.commit()
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


@router.patch("", response_model=ProfileResponse, dependencies=[Depends(verify_authenticated_csrf)])
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
