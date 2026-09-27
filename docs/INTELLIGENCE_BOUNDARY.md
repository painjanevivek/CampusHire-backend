# Reviewed intelligence boundary

CampusHire treats deterministic eligibility as authoritative and semantic relevance as optional evidence. `POST /api/v1/opportunities/{role_id}/match` never changes eligibility or application availability. It returns a versioned `available` result or an explicit `unavailable` state with a safe error code.

## Data minimization and versions

The student embedding projection includes department, target roles, declared skills, and reviewed resume summary/project/experience evidence. It excludes name, email, phone, PRN, institution identifiers, and external links. PostgreSQL stores the match fingerprint, component scores, model/version metadata, source profile revision, and source resume version; it does not store vectors or prompt text.

Qdrant remains a rebuildable projection. Every payload and query must include `institution_id`; callers use `tenant_vector_payload` and `tenant_query_filter`. A missing provider or dimension mismatch records a degraded result and leaves core recruitment operations available.

## Reviewed extraction

Role brief extraction creates a proposal only for draft roles. The source is retained as a SHA-256 fingerprint, not raw text. A T&P administrator must approve or reject the proposal with a reason. Only an approved proposal can update a draft role, and the audit log records the actor, provider, model, and prompt versions.

## Grounded policy evidence

Policy documents are versioned per institution. Draft or rejected sections never enter retrieval. Approval requires a reason, retires the previous approved version with the same title, and creates an audit event. Answers cite approved sections and return `grounded: false` when no approved evidence supports the question.

Provider outage recovery requires no data repair: eligibility, role management, applications, and manual policy review continue. Re-run semantic matching after provider recovery to obtain an available versioned result.

Successful results remain cached for their source fingerprint. Failed provider attempts have a
60-second negative-cache cooldown; a later normal match request can retry the same unchanged
profile, resume, and role. The existing failed row is locked and refreshed with the retry result
and evaluation time, avoiding a unique-fingerprint collision. A successful row is never replaced
by a later outage. This retry does not alter application snapshots or deterministic eligibility,
and the existing endpoint rate limit still applies. Dashboard reads do not call the provider.

The student dashboard shows a current cached semantic score when one exists for the exact
profile revision, generated resume version, role revision, and embedding model. Otherwise it
uses a local `profile-compatibility-v1` estimate when the published role lists skills: 80% role
skill coverage from the saved profile or reviewed generated resume, plus 20% target-role title
overlap. A role without published skills has no local score. This estimate makes no paid provider
call, does not change formal eligibility or application access, and is identified separately
from semantic matching in the dashboard. Scores below 60 are least compatible, 60–75 are
moderately compatible, and above 75 are compatible. These bands are preparation guidance,
not hiring probabilities.

The reviewed-resume projection now reads the generated resume's `accepted` content, including
skill groups, rather than expecting those fields at the top level. Its fingerprint version is
incremented so older cached matches cannot masquerade as scores from the corrected inputs.

The dashboard prioritizes currently published, formally eligible roles with an existing
application before other eligible roles. Closed roles and application history remain in the
Applications workspace.
