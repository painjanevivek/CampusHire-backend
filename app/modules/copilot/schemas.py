from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StudentIntent = Literal[
    "explain_eligibility",
    "explain_role_match",
    "improve_profile_or_resume",
    "preparation_roadmap",
]
TnpIntent = Literal[
    "draft_role_description",
    "extract_requirements",
    "draft_eligibility_rules",
    "detect_contradictions",
    "draft_announcement",
    "summarize_placement_funnel",
]


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", min_length=2, max_length=160)


class StudentMessageCreate(BaseModel):
    intent: StudentIntent
    message: str = Field(min_length=2, max_length=2000)
    role_id: UUID | None = None


class TnpMessageCreate(BaseModel):
    intent: TnpIntent
    message: str = Field(min_length=2, max_length=4000)


class Citation(BaseModel):
    source_type: str
    source_id: str
    label: str


class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    citations: list[Citation]
    missing_evidence: list[str]
    proposal_id: UUID | None
    created_at: datetime


class ConversationResponse(BaseModel):
    id: UUID
    audience: str
    title: str
    expires_at: datetime
    created_at: datetime
    messages: list[MessageResponse] = Field(default_factory=list)


class CopilotDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=2, max_length=6000)
    source_ids: list[str] = Field(default_factory=list, max_length=30)


class CopilotProposalEdit(BaseModel):
    expected_revision: int = Field(ge=1)
    content: CopilotDraft


class CopilotProposalDecision(BaseModel):
    expected_revision: int = Field(ge=1)
    decision: Literal["approve", "reject"]


class CopilotProposalResponse(BaseModel):
    id: UUID
    capability: str
    status: str
    revision: int
    content: CopilotDraft
    provider_name: str
    model_version: str
    prompt_version: str
    evidence_references: list[dict[str, object]]
    created_at: datetime
