# Eligibility Appeals and Manual Review — Operational Draft

## Product boundary

Deterministic, versioned rules decide formal eligibility. Missing evidence produces manual review instead of automatic rejection. Semantic match is advisory and cannot change eligibility. The product preserves rule versions, fact snapshots, explanations, status history, override reasons, and audit events.

CampusHire has no dedicated student appeal endpoint or case-management queue. The current administrator override route is restricted to `tnp_admin`, requires a reason, and accepts an optional policy reference. Therefore appeals must remain an institution-owned operational process, and a policy reference should be required procedurally until the API enforces it.

## Procedure

1. Receive the appeal through the approved institutional channel and issue an external case reference.
2. Verify the student and affected application without collecting credentials. Freeze the relevant application ID, rule-set version, fact snapshot, policy version, decision explanation, and correlation/audit references.
3. Assign a reviewer who did not make the disputed decision where staffing allows. Do not expose other applicants or protected attributes.
4. Classify the issue: incorrect current fact, missing evidence, rule interpretation, policy exception, system defect, or semantic-match concern.
5. Correct current evidence through supported workflows. Do not rewrite the historical snapshot; re-evaluate or append a reasoned decision according to approved policy.
6. An authorized `tnp_admin` records any override with case/policy reference and a student-safe reason. Semantic relevance alone is never a valid override basis.
7. Notify the student through the approved channel, state the outcome and evidence considered, and provide the escalation route.
8. Retain the case record according to the approved schedule and audit access.

## Stop conditions

Cross-tenant evidence, discrimination concerns, missing policy authority, security/privacy incidents, or an unavailable audit trail stop routine processing and escalate to the named privacy/legal, security, and T&P owners. No deadline or appeal right is claimed until the institution approves it.
