# CampusHire operational runbooks

Use `docs/INCIDENT_BREACH_COMMUNICATION.md` for the approval-draft incident matrix and `docs/OPERATIONAL_OWNERSHIP.md` for accountable contacts and coverage. Pending fields are release blockers, not implied assignments.

## Login outage

Check PostgreSQL and Redis readiness, then authentication error rate. Do not weaken CSRF, cookie, or rate-limit controls. If Redis is unavailable in production, authentication fails closed while existing health diagnostics remain available.

## AI provider outage

Open the AI circuit breaker, stop retry storms, and surface queued or failed status. Profiles, drives, applications, deterministic eligibility, and existing notifications remain available. Re-run only idempotent jobs after recovery.

## Queue backlog

Inspect `oldest_queued_age_seconds`, the oldest job, failure code, lease owner, attempt budget, and deduplication key. Scale workers only after identifying the slow dependency. Recover expired leases before replaying work, and never replay a business action without its idempotency key. Confirm the application/notification count is unchanged after recovery.

## Parser sandbox outage or timeout

Inspect only the safe parser code, job attempt, parser image digest, worker identity, duration, and launcher health; never attach the PDF or extracted text to logs or tickets. Confirm the approved image is available and the rootless launcher enforces no network, read-only root, dropped capabilities, `no-new-privileges`, non-root UID, and resource limits. `resume_parser_unavailable` and `resume_parser_timeout` requeue within the bounded attempt budget. Do not switch staging/production to the subprocess adapter. After recovery, retry only an authorized queued/failed job and verify that no `campushire-parser-*` container or disposable output directory remains.

## Database issue and restore

Stop writes and workers, capture the incident timestamp, and preserve the failed environment for investigation. Restore the latest verified PostgreSQL backup into a clean environment, run migrations, then compare the Alembic head, institution-scoped row counts, immutable application snapshots, audit events, queued-work timestamps, and private-object manifest references. Rehearse forward recovery and tenant-negative checks before reopening writes. Never overwrite the failed database until the restored copy is verified and the incident lead authorizes promotion.

## Dependency failure matrix

Use `scripts/rehearse_dependency_failures.py` for the synthetic local matrix and repeat its named scenarios in managed staging. Record start/end times, queue age, retries, terminal errors, business-object counts, and correlation IDs. Redis must fail closed for protected expensive operations; scanner/storage/parser failures must retain or safely terminate durable work; Gemini/Qdrant failures must not disable deterministic eligibility or core CRUD. Escalate rather than weakening a boundary to recover availability.

## Policy or matching incident

Disable the affected institution feature flag, preserve rule, prompt, and model versions and audit evidence, notify the named TNP owner, and revert to deterministic rules and manual review. Do not silently recalculate historical decisions.

## Security or privacy incident

Classify severity using affected tenants, data sensitivity, privilege gained, and active exploitation. Contain first: revoke affected sessions and credentials, disable the narrow route/provider/worker, and preserve immutable request IDs, audit events, deployment identifiers, and database/object-store evidence. Do not copy resume contents or secrets into tickets or chat. The named incident lead decides whether institutional and data-subject notification is required with qualified legal/privacy stakeholders. Recover from verified artifacts, validate tenant boundaries, rotate exposed credentials, monitor for recurrence, and complete a blameless retrospective with owned follow-up dates.

## Private-object deletion backlog

Inspect pseudonymous deletion request IDs, status, attempt count, safe error code, and oldest `available_at`. Restore the object-store dependency before scaling workers. Expired `processing` leases are recoverable and delete is idempotent; do not reconstruct deleted account records. A terminal `failed` record requires an authorized operator procedure and evidence that the opaque keys were removed before the request is closed.
