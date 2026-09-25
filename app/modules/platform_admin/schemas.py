from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlatformDashboardSummary(BaseModel):
    pending_institution_approvals: int
    active_institutions: int
    tnp_accounts: int
    unresolved_service_items: int
    overdue_escalations: int
    reporting_freshness_at: datetime | None


class PlatformInstitutionSummary(BaseModel):
    id: UUID
    code: str
    name: str
    is_active: bool
    timezone: str
    staff_count: int
    student_count: int
    application_count: int
    updated_at: datetime


class PlatformInstitutionPage(BaseModel):
    items: list[PlatformInstitutionSummary]
    page: int
    page_size: int
    total: int


class PlatformInstitutionDetail(PlatformInstitutionSummary):
    domains: list[str]
    drive_count: int


class InstitutionStatusChange(BaseModel):
    is_active: bool
    reason: str = Field(min_length=10, max_length=500)
    expected_updated_at: datetime | None = None


class PlatformStaffAccountCreate(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
    password: str = Field(min_length=12, max_length=128)
    role: Literal["tnp_admin", "tnp_reviewer", "tnp_auditor"]
    reason: str = Field(min_length=10, max_length=500)


class PlatformStaffAssignmentCreate(BaseModel):
    user_id: UUID | None = None
    username: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
    role: Literal["tnp_admin", "tnp_reviewer", "tnp_auditor"]
    reason: str = Field(min_length=10, max_length=500)

    @model_validator(mode="after")
    def require_one_identity(self) -> "PlatformStaffAssignmentCreate":
        if (self.user_id is None) == (self.username is None):
            raise ValueError("Provide exactly one staff user ID or username")
        return self


class PlatformStaffAccount(BaseModel):
    id: UUID
    institution_id: UUID
    user_id: UUID
    username: str | None
    email: str
    role: str
    status: str
    requires_terms_acceptance: bool


class PlatformStaffStatusChange(BaseModel):
    status: Literal["active", "suspended", "revoked"]
    role: Literal["tnp_admin", "tnp_reviewer", "tnp_auditor"] | None = None
    reason: str = Field(min_length=10, max_length=500)


class PlatformReportSummary(BaseModel):
    institution_count: int
    student_count: int
    drive_count: int
    application_count: int
    applications_by_status: dict[str, int]
    generated_at: datetime
    provisional: bool = True


class PlatformDriveInstance(BaseModel):
    id: UUID
    opens_at: datetime
    deadline_at: datetime
    status: str


class PlatformDriveInstitutionBreakdown(BaseModel):
    institution_id: UUID
    institution_name: str
    drive_ids: list[UUID]
    drives: list[PlatformDriveInstance]
    application_count: int
    student_count: int


class PlatformDriveGroup(BaseModel):
    company_name: str
    drive_title: str
    cycle_year: int
    drive_count: int
    application_count: int
    student_count: int
    institutions: list[PlatformDriveInstitutionBreakdown]


class PlatformDriveGroupPage(BaseModel):
    items: list[PlatformDriveGroup]
    page: int
    page_size: int
    total: int
    generated_at: datetime


class PlatformDriveApplicant(BaseModel):
    application_id: UUID
    drive_id: UUID
    institution_id: UUID
    institution_name: str
    student_user_id: UUID
    student_name: str
    prn: str | None
    prn_verified: bool
    role_title: str
    application_status: str
    submitted_at: datetime


class PlatformDriveApplicantPage(BaseModel):
    items: list[PlatformDriveApplicant]
    page: int
    page_size: int
    total: int


class PlatformApplicationEvidence(BaseModel):
    applicant: PlatformDriveApplicant
    profile_snapshot: dict[str, object]
    resume_snapshot: dict[str, object]
    facts_snapshot: dict[str, object]
    eligibility_snapshot: dict[str, object]
    application_form_snapshot: dict[str, object]
    acknowledgment_snapshot: dict[str, object]
    disclosure_status: str
    evidence_provenance: str


class PlatformNoticeCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=180)
    message: str = Field(min_length=3, max_length=2_000)
    to_tnp: bool = False
    to_students: bool = False

    @model_validator(mode="after")
    def require_audience(self) -> "PlatformNoticeCreate":
        if not self.to_tnp and not self.to_students:
            raise ValueError("Select at least one notice audience")
        if not self.subject.strip() or not self.message.strip():
            raise ValueError("Subject and notice cannot be blank")
        self.subject = self.subject.strip()
        self.message = self.message.strip()
        return self


class PlatformNoticeDelivery(BaseModel):
    notice_id: UUID
    tnp_recipients: int
    student_recipients: int


class ServiceQueueStatus(BaseModel):
    service: str
    pending: int
    failed: int
    oldest_outstanding_at: datetime | None


class PlatformHealthSummary(BaseModel):
    status: Literal["healthy", "degraded"]
    queues: list[ServiceQueueStatus]
    checked_at: datetime


class PlatformSettingsResponse(BaseModel):
    ai_provider: str
    ai_model: str | None
    ai_key_configured: bool
    email_configured: bool
    storage_backend: str
    platform_notice: dict[str, object]
    service_targets: dict[str, object]
    feature_availability: dict[str, object]


class PlatformSettingsUpdate(BaseModel):
    platform_notice: dict[str, object] | None = None
    service_targets: dict[str, object] | None = None
    feature_availability: dict[str, object] | None = None


class PlatformAdminAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    revision: int
    assigned_at: datetime


class PlatformAdminTransferRequest(BaseModel):
    user_id: UUID
    expected_revision: int
    reason: str = Field(min_length=10, max_length=500)
