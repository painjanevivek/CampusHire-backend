from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.models.auth import UserRole
from app.modules.application_packets.schemas import (
    ApplicationDisclosureResponse,
    ApplicationDraftResponse,
    ApplicationFormResponse,
    ApplicationFormUpdate,
    ApplicationReviewResponse,
    DraftDisclosureUpdate,
    DraftProfileConfirmation,
    DraftResumeUpdate,
    DraftSubmitRequest,
)
from app.modules.application_packets.service import (
    ApplicationPacketError,
    confirm_draft_profile,
    create_or_resume_draft,
    delete_draft,
    draft_response,
    form_response,
    get_application_form,
    get_draft,
    publish_application_form,
    read_compliance_disclosure,
    read_student_disclosure,
    review_draft,
    save_draft_disclosures,
    select_draft_resume,
    submit_draft,
    upsert_application_form,
)
from app.modules.audit.service import record_audit_event
from app.modules.auth.dependencies import (
    CurrentPrincipal,
    CurrentTenant,
    Database,
    require_permissions,
    require_recent_reauthentication,
    require_roles,
    verify_authenticated_csrf,
)
from app.modules.communications.service import record_product_event
from app.modules.recruitment.schemas import ApplicationResponse
from app.modules.recruitment.service import response_for_application

student_router = APIRouter(dependencies=[Depends(require_roles(UserRole.STUDENT.value))])
admin_router = APIRouter(
    prefix="/admin/recruitment",
    dependencies=[Depends(require_permissions("recruitment.read"))],
)
compliance_router = APIRouter(
    prefix="/admin/compliance",
    dependencies=[Depends(require_permissions("applications.disclosures.read"))],
)


def _http_error(error: ApplicationPacketError) -> HTTPException:
    code = str(error)
    if code.endswith("_not_found"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=code)
    if code in {
        "application_draft_revision_conflict",
        "profile_revision_conflict",
        "submitted_application_draft_immutable",
    }:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=code)
    if code == "application_draft_expired":
        return HTTPException(status_code=status.HTTP_410_GONE, detail=code)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=code)


@student_router.post(
    "/opportunities/{role_id}/application-draft",
    response_model=ApplicationDraftResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def start_application_draft(
    request: Request, role_id: UUID, db: Database, tenant: CurrentTenant
) -> ApplicationDraftResponse:
    try:
        draft = await create_or_resume_draft(db, tenant.institution_id, tenant.user_id, role_id)
        response = await draft_response(db, draft)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    record_audit_event(
        db,
        event_type="application.draft_started",
        actor_user_id=tenant.user_id,
        institution_id=tenant.institution_id,
        resource_type="application_draft",
        resource_id=str(draft.id),
        correlation_id=request.state.correlation_id,
        details={"role_id": str(role_id)},
    )
    await db.commit()
    return response


@student_router.get("/application-drafts/{draft_id}", response_model=ApplicationDraftResponse)
async def read_application_draft(
    draft_id: UUID, db: Database, tenant: CurrentTenant
) -> ApplicationDraftResponse:
    try:
        return await get_draft(db, tenant.institution_id, tenant.user_id, draft_id)
    except ApplicationPacketError as error:
        raise _http_error(error) from error


@student_router.put(
    "/application-drafts/{draft_id}/resume",
    response_model=ApplicationDraftResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_application_resume(
    draft_id: UUID,
    payload: DraftResumeUpdate,
    db: Database,
    tenant: CurrentTenant,
) -> ApplicationDraftResponse:
    try:
        draft = await select_draft_resume(
            db,
            tenant.institution_id,
            tenant.user_id,
            draft_id,
            payload.resume_version_id,
            payload.expected_revision,
        )
        response = await draft_response(db, draft)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    await db.commit()
    return response


@student_router.put(
    "/application-drafts/{draft_id}/profile-confirmation",
    response_model=ApplicationDraftResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_application_profile(
    draft_id: UUID,
    payload: DraftProfileConfirmation,
    db: Database,
    tenant: CurrentTenant,
) -> ApplicationDraftResponse:
    try:
        draft = await confirm_draft_profile(
            db,
            tenant.institution_id,
            tenant.user_id,
            draft_id,
            payload.profile_revision,
            payload.expected_revision,
        )
        response = await draft_response(db, draft)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    await db.commit()
    return response


@student_router.put(
    "/application-drafts/{draft_id}/disclosures",
    response_model=ApplicationDraftResponse,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def update_application_disclosures(
    draft_id: UUID,
    payload: DraftDisclosureUpdate,
    db: Database,
    tenant: CurrentTenant,
) -> ApplicationDraftResponse:
    try:
        draft = await save_draft_disclosures(
            db,
            tenant.institution_id,
            tenant.user_id,
            draft_id,
            payload.answers,
            payload.expected_revision,
        )
        response = await draft_response(db, draft)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    await db.commit()
    return response


@student_router.get(
    "/application-drafts/{draft_id}/review", response_model=ApplicationReviewResponse
)
async def read_application_review(
    draft_id: UUID, db: Database, tenant: CurrentTenant
) -> ApplicationReviewResponse:
    try:
        return await review_draft(db, tenant.institution_id, tenant.user_id, draft_id)
    except ApplicationPacketError as error:
        raise _http_error(error) from error


@student_router.post(
    "/application-drafts/{draft_id}/submit",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def submit_application_draft(
    request: Request,
    draft_id: UUID,
    payload: DraftSubmitRequest,
    db: Database,
    tenant: CurrentTenant,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=80)],
) -> ApplicationResponse | JSONResponse:
    try:
        application, replayed = await submit_draft(
            db,
            tenant.institution_id,
            tenant.user_id,
            draft_id,
            payload.expected_revision,
            idempotency_key,
        )
        response = await response_for_application(db, application)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    if not replayed:
        await record_product_event(
            db,
            event_name="first_application_submitted",
            route_group="application_wizard",
            institution_id=tenant.institution_id,
            dedupe_key=f"first-application:{tenant.user_id}",
        )
        record_audit_event(
            db,
            event_type="application.submitted",
            actor_user_id=tenant.user_id,
            institution_id=tenant.institution_id,
            resource_type="application",
            resource_id=str(application.id),
            correlation_id=request.state.correlation_id,
            details={
                "role_id": str(application.role_id),
                "resume_version_id": str(application.resume_version_id),
                "draft_id": str(draft_id),
                "disclosure_status": application.disclosure_status,
            },
        )
    await db.commit()
    if replayed:
        return JSONResponse(response.model_dump(mode="json"), status_code=status.HTTP_200_OK)
    return response


@student_router.delete(
    "/application-drafts/{draft_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(verify_authenticated_csrf)],
)
async def discard_application_draft(draft_id: UUID, db: Database, tenant: CurrentTenant) -> None:
    try:
        await delete_draft(db, tenant.institution_id, tenant.user_id, draft_id)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    await db.commit()


@student_router.get(
    "/applications/{application_id}/disclosures",
    response_model=ApplicationDisclosureResponse,
)
async def read_own_application_disclosures(
    application_id: UUID,
    response: Response,
    db: Database,
    tenant: CurrentTenant,
) -> ApplicationDisclosureResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await read_student_disclosure(
            db, tenant.institution_id, tenant.user_id, application_id
        )
    except ApplicationPacketError as error:
        raise _http_error(error) from error


@admin_router.get(
    "/roles/{role_id}/application-form",
    response_model=ApplicationFormResponse | None,
)
async def read_role_application_form(
    role_id: UUID, db: Database, principal: CurrentPrincipal
) -> ApplicationFormResponse | None:
    try:
        return await get_application_form(db, principal.institution_id, role_id)
    except ApplicationPacketError as error:
        raise _http_error(error) from error


@admin_router.put(
    "/roles/{role_id}/application-form",
    response_model=ApplicationFormResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def save_role_application_form(
    request: Request,
    role_id: UUID,
    payload: ApplicationFormUpdate,
    db: Database,
    principal: CurrentPrincipal,
) -> ApplicationFormResponse:
    try:
        form = await upsert_application_form(
            db,
            principal.institution_id,
            role_id,
            principal.user.id,
            payload,
        )
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    record_audit_event(
        db,
        event_type="application_form.saved",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="role_application_form",
        resource_id=str(form.id),
        correlation_id=request.state.correlation_id,
        details={"role_id": str(role_id), "version": form.version},
    )
    await db.commit()
    return form_response(form)


@admin_router.post(
    "/roles/{role_id}/application-form/publish",
    response_model=ApplicationFormResponse,
    dependencies=[
        Depends(verify_authenticated_csrf),
        Depends(require_permissions("recruitment.manage")),
    ],
)
async def publish_role_application_form(
    request: Request,
    role_id: UUID,
    db: Database,
    principal: CurrentPrincipal,
) -> ApplicationFormResponse:
    try:
        form = await publish_application_form(db, principal.institution_id, role_id)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    record_audit_event(
        db,
        event_type="application_form.published",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="role_application_form",
        resource_id=str(form.id),
        correlation_id=request.state.correlation_id,
        details={"role_id": str(role_id), "version": form.version},
    )
    await db.commit()
    return form_response(form)


@compliance_router.get(
    "/applications/{application_id}/disclosures",
    response_model=ApplicationDisclosureResponse,
    dependencies=[Depends(require_recent_reauthentication)],
)
async def read_application_disclosures_for_compliance(
    request: Request,
    application_id: UUID,
    response: Response,
    db: Database,
    principal: CurrentPrincipal,
) -> ApplicationDisclosureResponse:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        disclosure = await read_compliance_disclosure(db, principal.institution_id, application_id)
    except ApplicationPacketError as error:
        raise _http_error(error) from error
    record_audit_event(
        db,
        event_type="application_disclosure.viewed",
        actor_user_id=principal.user.id,
        institution_id=principal.institution_id,
        resource_type="application_disclosure",
        resource_id=str(application_id),
        correlation_id=request.state.correlation_id,
        details={"access_scope": "compliance_only"},
    )
    await db.commit()
    return disclosure
