# Reviewed intelligence boundary

CampusHire treats deterministic eligibility as authoritative and semantic relevance as optional evidence. `GET /api/v1/opportunities/{role_id}/match` never changes eligibility or application availability. It returns a versioned `available` result or an explicit `unavailable` state with a safe error code.

## Data minimization and versions

The student embedding projection includes department, target roles, declared skills, and reviewed resume summary/project/experience evidence. It excludes name, email, phone, PRN, institution identifiers, and external links. PostgreSQL stores the match fingerprint, component scores, model/version metadata, source profile revision, and source resume version; it does not store vectors or prompt text.

Qdrant remains a rebuildable projection. Every payload and query must include `institution_id`; callers use `tenant_vector_payload` and `tenant_query_filter`. A missing provider or dimension mismatch records a degraded result and leaves core recruitment operations available.

## Reviewed extraction

Role brief extraction creates a proposal only for draft roles. The source is retained as a SHA-256 fingerprint, not raw text. A T&P administrator must approve or reject the proposal with a reason. Only an approved proposal can update a draft role, and the audit log records the actor, provider, model, and prompt versions.

## Grounded policy evidence

Policy documents are versioned per institution. Draft or rejected sections never enter retrieval. Approval requires a reason, retires the previous approved version with the same title, and creates an audit event. Answers cite approved sections and return `grounded: false` when no approved evidence supports the question.

Provider outage recovery requires no data repair: eligibility, role management, applications, and manual policy review continue. Re-run semantic matching after provider recovery to create a new versioned result.
