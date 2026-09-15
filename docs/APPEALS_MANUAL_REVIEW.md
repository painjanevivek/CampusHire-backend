# Eligibility Appeals and Independent Review

## Product boundary

Deterministic, versioned rules decide formal eligibility. Missing evidence produces manual review instead of automatic rejection. Semantic match is advisory and cannot change eligibility. The product preserves rule versions, fact snapshots, explanations, status history, override reasons, and audit events.

CampusHire provides an institution-scoped appeal case with an assignee, due date, revision, escalation state, structured resolution, and append-only assignment history. The disputed decision actor is recorded and cannot resolve the appeal. The Platform Admin may arrange staffing through an audited reassignment but cannot resolve the merits.

## Procedure

1. Receive the appeal through the Student workspace and preserve the generated case reference.
2. Verify the student and affected application without collecting credentials. Freeze the relevant application ID, rule-set version, fact snapshot, policy version, decision explanation, and correlation/audit references.
3. Assign a Reviewer or Officer who did not make the disputed decision. Claim and reassignment use an atomic revision check. Do not expose other applicants or protected attributes.
4. Classify the issue: incorrect current fact, missing evidence, rule interpretation, policy exception, system defect, or semantic-match concern.
5. Correct current evidence through supported workflows. Do not rewrite the historical snapshot; re-evaluate or append a reasoned decision according to approved policy.
6. An authorised Officer records any exceptional override with a required policy reference and student-safe reason. Semantic relevance alone is never a valid override basis.
7. Notify the Student through a permission-checked destination and show the owner/team, due date, result, and escalation state.
8. Retain the case record according to the approved schedule and audit access.

## Stop conditions

Cross-tenant evidence, discrimination concerns, missing policy authority, security/privacy incidents, or an unavailable audit trail stop routine processing and escalate to the named privacy/legal, security, and T&P owners. If no independent reviewer is available, the case remains explicitly waiting/escalated; it is never silently assigned to the disputed decision-maker.
