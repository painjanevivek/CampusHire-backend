from fastapi import APIRouter

from app.api.v1.routes.admin_recruitment import router as admin_recruitment_router
from app.api.v1.routes.application_packets import admin_router as application_packet_admin_router
from app.api.v1.routes.application_packets import compliance_router
from app.api.v1.routes.application_packets import (
    student_router as application_packet_student_router,
)
from app.api.v1.routes.audit import router as audit_router
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.communications import router as communications_router
from app.api.v1.routes.engagement import admin_router as admin_engagement_router
from app.api.v1.routes.engagement import student_router as student_engagement_router
from app.api.v1.routes.experience import admin_router as admin_experience_router
from app.api.v1.routes.experience import student_router as student_experience_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.institutions import operator_router
from app.api.v1.routes.institutions import router as institutions_router
from app.api.v1.routes.intelligence import admin_router as admin_intelligence_router
from app.api.v1.routes.intelligence import student_router as student_intelligence_router
from app.api.v1.routes.operations import router as operations_router
from app.api.v1.routes.opportunities import router as opportunities_router
from app.api.v1.routes.privacy import router as privacy_router
from app.api.v1.routes.profiles import router as profiles_router
from app.api.v1.routes.resumes import router as resumes_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(communications_router, tags=["communications and guidance"])
api_router.include_router(institutions_router, tags=["institution memberships"])
api_router.include_router(operator_router, tags=["institution provisioning"])
api_router.include_router(profiles_router, tags=["student profile"])
api_router.include_router(privacy_router, tags=["privacy"])
api_router.include_router(resumes_router, tags=["resumes"])
api_router.include_router(opportunities_router, tags=["opportunities and applications"])
api_router.include_router(application_packet_student_router, tags=["application packets"])
api_router.include_router(student_engagement_router, tags=["readiness and communication"])
api_router.include_router(student_intelligence_router, tags=["semantic relevance"])
api_router.include_router(admin_recruitment_router, tags=["placement administration"])
api_router.include_router(application_packet_admin_router, tags=["placement administration"])
api_router.include_router(compliance_router, tags=["application compliance"])
api_router.include_router(audit_router, tags=["audit"])
api_router.include_router(admin_intelligence_router, tags=["reviewed intelligence"])
api_router.include_router(admin_engagement_router, tags=["placement communication"])
api_router.include_router(operations_router, tags=["operations"])
api_router.include_router(admin_experience_router, tags=["placement experience"])
api_router.include_router(student_experience_router, tags=["student experience"])
