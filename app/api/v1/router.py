from fastapi import APIRouter

from app.api.v1.routes.admin_recruitment import router as admin_recruitment_router
from app.api.v1.routes.agentic import student_router as student_agentic_router
from app.api.v1.routes.agentic import tnp_router as tnp_agentic_router
from app.api.v1.routes.application_packets import admin_router as application_packet_admin_router
from app.api.v1.routes.application_packets import compliance_router
from app.api.v1.routes.application_packets import (
    student_router as application_packet_student_router,
)
from app.api.v1.routes.audit import router as audit_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.communications import router as communications_router
from app.api.v1.routes.copilot import student_router as student_copilot_router
from app.api.v1.routes.copilot import tnp_router as tnp_copilot_router
from app.api.v1.routes.engagement import admin_router as admin_engagement_router
from app.api.v1.routes.engagement import student_router as student_engagement_router
from app.api.v1.routes.experience import admin_router as admin_experience_router
from app.api.v1.routes.experience import student_router as student_experience_router
from app.api.v1.routes.generative import router as generative_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.institutions import operator_router
from app.api.v1.routes.institutions import router as institutions_router
from app.api.v1.routes.intelligence import admin_router as admin_intelligence_router
from app.api.v1.routes.intelligence import student_router as student_intelligence_router
from app.api.v1.routes.onboarding import admin_router as admin_onboarding_router
from app.api.v1.routes.onboarding import student_router as student_onboarding_router
from app.api.v1.routes.operations import router as operations_router
from app.api.v1.routes.opportunities import router as opportunities_router
from app.api.v1.routes.platform import router as platform_router
from app.api.v1.routes.privacy import router as privacy_router
from app.api.v1.routes.privacy import tnp_router as tnp_privacy_router
from app.api.v1.routes.profiles import router as profiles_router
from app.api.v1.routes.registrations import operator_router as registration_operator_router
from app.api.v1.routes.registrations import public_router as registration_public_router
from app.api.v1.routes.resumes import router as resumes_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(registration_public_router, tags=["authentication"])
api_router.include_router(registration_operator_router, tags=["institution provisioning"])
api_router.include_router(communications_router, tags=["communications and guidance"])
api_router.include_router(institutions_router, tags=["institution memberships"])
api_router.include_router(operator_router, tags=["institution provisioning"])
api_router.include_router(profiles_router, tags=["student profile"])
api_router.include_router(student_onboarding_router, tags=["student onboarding"])
api_router.include_router(
    admin_onboarding_router, prefix="/tnp", tags=["institution onboarding"]
)
api_router.include_router(
    admin_onboarding_router,
    prefix="/admin",
    tags=["institution onboarding compatibility"],
    include_in_schema=False,
)
api_router.include_router(privacy_router, tags=["privacy"])
api_router.include_router(tnp_privacy_router, tags=["privacy administration"])
api_router.include_router(platform_router, tags=["platform administration"])
api_router.include_router(resumes_router, tags=["resumes"])
api_router.include_router(generative_router, tags=["generative resume studio"])
api_router.include_router(student_copilot_router, tags=["student copilot"])
api_router.include_router(tnp_copilot_router, tags=["T&P copilot"])
api_router.include_router(student_agentic_router, tags=["student agent workflows"])
api_router.include_router(tnp_agentic_router, tags=["T&P agent workflows"])
api_router.include_router(opportunities_router, tags=["opportunities and applications"])
api_router.include_router(application_packet_student_router, tags=["application packets"])
api_router.include_router(student_engagement_router, tags=["readiness and communication"])
api_router.include_router(student_intelligence_router, tags=["semantic relevance"])
api_router.include_router(
    admin_recruitment_router, prefix="/tnp", tags=["placement administration"]
)
api_router.include_router(
    admin_recruitment_router,
    prefix="/admin",
    tags=["placement administration compatibility"],
    include_in_schema=False,
)
api_router.include_router(application_packet_admin_router, tags=["placement administration"])
api_router.include_router(compliance_router, tags=["application compliance"])
api_router.include_router(audit_router, tags=["audit"])
api_router.include_router(admin_intelligence_router, tags=["reviewed intelligence"])
api_router.include_router(admin_engagement_router, tags=["placement communication"])
api_router.include_router(operations_router, tags=["operations"])
api_router.include_router(
    admin_experience_router, prefix="/tnp", tags=["placement experience"]
)
api_router.include_router(
    admin_experience_router,
    prefix="/admin",
    tags=["placement experience compatibility"],
    include_in_schema=False,
)
api_router.include_router(student_experience_router, tags=["student experience"])
