from dataclasses import dataclass


@dataclass(frozen=True)
class PromptTemplate:
    capability: str
    version: str
    instructions: str


RESUME_CONTENT_V1 = PromptTemplate(
    capability="resume_content",
    version="resume-content-v1",
    instructions=(
        "Draft concise professional resume content using only the supplied evidence. "
        "Every claim must cite one or more exact evidence IDs. Do not infer metrics, awards, "
        "seniority, outcomes, certifications, or responsibilities. If evidence is insufficient, "
        "omit the claim. Return only JSON matching the provided schema."
    ),
)


PROMPT_REGISTRY = {(RESUME_CONTENT_V1.capability, RESUME_CONTENT_V1.version): RESUME_CONTENT_V1}
