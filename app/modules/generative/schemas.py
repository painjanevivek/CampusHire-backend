from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GroundedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=2, max_length=900)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class ResumeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    professional_summary: GroundedClaim | None = None
    education: list[GroundedClaim] = Field(default_factory=list, max_length=12)
    project_bullets: list[GroundedClaim] = Field(default_factory=list, max_length=20)
    experience_bullets: list[GroundedClaim] = Field(default_factory=list, max_length=20)
    skills: list[GroundedClaim] = Field(default_factory=list, max_length=40)


class EvidenceReference(BaseModel):
    evidence_id: str
    kind: str
    label: str
    facts: str


class ResumeEvidenceResponse(BaseModel):
    evidence: list[EvidenceReference]


class ResumeProposalCreate(BaseModel):
    selected_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    purpose_role_id: UUID | None = None


class ProposalEditRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    content: ResumeDraft


class ProposalDecisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    decision: Literal["accept", "reject"]


class ProposalResponse(BaseModel):
    id: UUID
    capability: str
    purpose_role_id: UUID | None
    status: str
    revision: int
    content: ResumeDraft
    evidence_references: list[EvidenceReference]
    evidence_digest: str
    provider_name: str
    model_version: str
    prompt_version: str
    created_at: datetime
    accepted_at: datetime | None
    rejected_at: datetime | None


class ResumeVersionMaterializeRequest(BaseModel):
    parent_version_id: UUID | None = None
