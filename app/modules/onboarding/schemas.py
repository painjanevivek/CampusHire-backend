from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.modules.auth.placement_access import normalize_prn


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StudentIdentityStep(StrictModel):
    full_name: str = Field(min_length=2, max_length=160)
    prn: str = Field(min_length=2, max_length=64)
    department: str = Field(min_length=2, max_length=120)
    graduation_year: int = Field(ge=2000, le=2100)

    @field_validator("prn")
    @classmethod
    def validate_prn(cls, value: str) -> str:
        try:
            return normalize_prn(value)
        except ValueError as error:
            raise ValueError("Enter a PRN in the institution's registered format") from error


class EducationEntry(StrictModel):
    qualification_level: Literal["degree", "class_10", "class_12", "diploma"]
    degree: str = Field(min_length=2, max_length=120)
    branch: str = Field(min_length=2, max_length=120)
    institution: str = Field(min_length=2, max_length=200)
    start_year: int | None = Field(default=None, ge=1990, le=2100)
    graduation_year: int = Field(ge=1990, le=2100)
    score: float = Field(ge=0, le=100)
    score_scale: Literal["cgpa_10", "percentage"]
    active_backlogs: int = Field(default=0, ge=0, le=100)


class ExperienceEntry(StrictModel):
    organization: str = Field(min_length=2, max_length=200)
    title: str = Field(min_length=2, max_length=160)
    start_date: date
    end_date: date | None = None
    is_current: bool = False
    responsibilities: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_dates(self) -> "ExperienceEntry":
        if self.is_current and self.end_date is not None:
            raise ValueError("A current experience cannot have an end date")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("The end date cannot precede the start date")
        return self


class ProjectEntry(StrictModel):
    title: str = Field(min_length=2, max_length=160)
    project_type: Literal["academic", "personal", "internship", "hackathon", "other"] = "other"
    description: str = Field(min_length=10, max_length=300)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    outcomes: list[str] = Field(default_factory=list, max_length=12)
    project_url: AnyHttpUrl | None = None


class ProjectEntryResponse(StrictModel):
    id: UUID
    title: str = Field(min_length=2, max_length=160)
    project_type: Literal["academic", "personal", "internship", "hackathon", "other"]
    description: str = Field(min_length=10, max_length=300)
    technologies: list[str] = Field(max_length=30)
    outcomes: list[str] = Field(max_length=12)
    project_url: AnyHttpUrl | None


class CertificationEntry(StrictModel):
    name: str = Field(min_length=2, max_length=200)
    issuer: str = Field(min_length=2, max_length=200)
    issued_on: date | None = None
    expires_on: date | None = None
    credential_url: AnyHttpUrl | None = None


class ProjectsSkillsStep(StrictModel):
    projects: list[ProjectEntry] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=40)
    certifications: list[CertificationEntry] = Field(default_factory=list, max_length=20)


class CareerPreferenceStep(StrictModel):
    target_roles: list[str] = Field(min_length=1, max_length=10)
    industries: list[str] = Field(default_factory=list, max_length=10)
    locations: list[str] = Field(default_factory=list, max_length=20)
    job_types: list[Literal["full_time", "internship", "contract"]] = Field(
        default_factory=list, max_length=3
    )
    work_modes: list[Literal["onsite", "hybrid", "remote"]] = Field(
        default_factory=list, max_length=3
    )


class PlacementParticipationStep(StrictModel):
    placement_cycle: str = Field(min_length=2, max_length=120)
    communication_channels: list[Literal["email", "in_app"]] = Field(min_length=1)
    visibility: Literal["placement_team", "participating_recruiters"]
    privacy_accepted: Literal[True]


class ReviewStep(StrictModel):
    confirmed: Literal[True]


class StudentOnboardingUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    step: Literal[1, 2, 3, 4, 5, 6, 7]
    identity: StudentIdentityStep | None = None
    education: list[EducationEntry] | None = Field(default=None, max_length=8)
    experience: list[ExperienceEntry] | None = Field(default=None, max_length=20)
    projects_skills: ProjectsSkillsStep | None = None
    career_preferences: CareerPreferenceStep | None = None
    placement_participation: PlacementParticipationStep | None = None
    review: ReviewStep | None = None

    @model_validator(mode="after")
    def require_step_payload(self) -> "StudentOnboardingUpdate":
        fields = {
            1: self.identity,
            2: self.education,
            3: self.experience,
            4: self.projects_skills,
            5: self.career_preferences,
            6: self.placement_participation,
            7: self.review,
        }
        # Experience and projects/skills are optional steps and may be skipped empty.
        if self.step not in {3, 4} and fields[self.step] is None:
            raise ValueError(f"Step {self.step} data is required")
        if self.step == 2 and not self.education:
            raise ValueError("At least one education record is required")
        return self


class StudentOnboardingResponse(StrictModel):
    profile_id: UUID
    institution_id: UUID | None
    institution_name: str | None
    revision: int
    current_step: int
    completed: bool
    completed_at: datetime | None
    identity: dict[str, object]
    education: list[dict[str, object]]
    experience: list[dict[str, object]]
    projects: list[ProjectEntryResponse]
    skills: list[dict[str, object]]
    certifications: list[dict[str, object]]
    career_preferences: dict[str, object] | None
    placement_participation: dict[str, object] | None


class CampusProgram(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    branches: list[str] = Field(min_length=1, max_length=50)
    graduating_batches: list[int] = Field(min_length=1, max_length=20)


class CampusEntry(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    programs: list[CampusProgram] = Field(min_length=1, max_length=30)


class AdminIdentityStep(StrictModel):
    administrator_name: str = Field(min_length=2, max_length=160)


class InstitutionIdentityStep(StrictModel):
    official_name: str = Field(min_length=2, max_length=200)
    domain: str = Field(min_length=3, max_length=255)


class PlacementCycleStep(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    starts_on: date
    ends_on: date
    participating_cohorts: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_dates(self) -> "PlacementCycleStep":
        if self.ends_on < self.starts_on:
            raise ValueError("Placement cycle end date cannot precede its start date")
        return self


class RosterInvitationStep(StrictModel):
    roster_import_id: UUID | None = None
    invitation_mode: Literal["roster_only", "roster_and_verified_domain"]


class PolicyPermissionStep(StrictModel):
    eligibility_template_names: list[str] = Field(default_factory=list, max_length=30)
    policy_names: list[str] = Field(default_factory=list, max_length=30)
    approval_roles: list[Literal["tnp_owner", "tnp_admin", "tnp_reviewer"]] = Field(
        default_factory=list, max_length=3
    )


class InstitutionReviewStep(StrictModel):
    invite_team_emails: list[EmailStr] = Field(default_factory=list, max_length=20)
    activate_institution: Literal[True]


class InstitutionOnboardingUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    step: Literal[1, 2, 3, 4, 5, 6, 7]
    administrator: AdminIdentityStep | None = None
    institution: InstitutionIdentityStep | None = None
    campuses: list[CampusEntry] | None = Field(default=None, max_length=20)
    placement_cycle: PlacementCycleStep | None = None
    roster: RosterInvitationStep | None = None
    policies: PolicyPermissionStep | None = None
    review: InstitutionReviewStep | None = None

    @model_validator(mode="after")
    def require_step_payload(self) -> "InstitutionOnboardingUpdate":
        fields = {
            1: self.administrator,
            2: self.institution,
            3: self.campuses,
            4: self.placement_cycle,
            5: self.roster,
            6: self.policies,
            7: self.review,
        }
        if fields[self.step] is None:
            raise ValueError(f"Step {self.step} data is required")
        if self.step == 3 and not self.campuses:
            raise ValueError("At least one campus is required")
        return self


class InstitutionOnboardingResponse(StrictModel):
    institution_id: UUID
    institution_name: str
    institution_active: bool
    revision: int
    current_step: int
    completed_steps: list[int]
    step_data: dict[str, object]
    activated_at: datetime | None
