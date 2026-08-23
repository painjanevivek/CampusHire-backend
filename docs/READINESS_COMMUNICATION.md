# Readiness and communication

## Curated roadmap boundary

CampusHire ships eight approved version-1 paths: Software, Frontend, Backend, Full-Stack, Mobile Application, Data Analyst, Machine Learning, and AI Engineer. Templates are validated as directed acyclic graphs before persistence. Students may complete only nodes whose prerequisites are complete, and progress records attach bounded evidence metadata with safe internal references.

A selected template version is preserved with the student roadmap. Switching paths after progress exists is rejected until an explicit future reset workflow is reviewed; progress is never silently discarded. Completing a milestone records evidence—it does not assert proficiency or predict employment.

## One-next-action policy

`GET /api/v1/dashboard` evaluates `readiness-v1` with deterministic priority and tie-breaking:

1. required profile facts;
2. reviewed resume extraction;
3. completed clean resume;
4. project evidence;
5. selected curated roadmap;
6. first prerequisite-ready roadmap milestone;
7. eligible opportunity review.

The response contains exactly one action, its reason, internal destination, policy version, and source facts. The readiness percentage is component completion—not a hiring probability or skill score. Eligibility and semantic relevance remain separate.

## Notification safety

In-app notifications are institution- and recipient-scoped. `(recipient_user_id, event_key)` is unique so worker or HTTP retries cannot duplicate a message. Deep links must begin with one `/`; protocol-relative, external, and backslash paths are rejected before persistence.

Application status changes publish deduplicated updates inside the same transaction as the status history and audit record. Administrators may publish constructive feedback; students explicitly mark updates read before following the internal destination. Core status data remains available if notification delivery fails and can be reconciled from authoritative application events.
