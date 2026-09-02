# CampusHire operational runbooks

Use `docs/INCIDENT_BREACH_COMMUNICATION.md` for the approval-draft incident matrix and `docs/OPERATIONAL_OWNERSHIP.md` for accountable contacts and coverage. Pending fields are release blockers, not implied assignments.

## Startup, deployment, and shutdown

Before startup, verify the dedicated-host attestation, protected environment/secret permissions,
owned-domain DNS/TLS reachability, parser mTLS directory, latest off-host backup age, object quota,
and immutable image references. Run `python3 -m scripts.validate_production_environment` and
`deploy/production/deploy.sh`; do not call Compose directly because that bypasses the host,
environment, quota, and ready checks. Record the release-manifest ID and every image digest.

For graceful shutdown, pause new uploads and institution onboarding, stop the worker first, wait for
active job leases to finish or expire safely, stop API/frontend/gateway writes, create and verify an
encrypted off-host recovery bundle, then stop stateful containers. Keep data-rights/support
communication available through the approved incident channel. Startup reverses this order:
PostgreSQL/Redis/Qdrant/ClamAV, migration, API, worker, frontend, gateway, then the operations probe.

Rollback changes application images/configuration only. Confirm migration compatibility against the
approved rollback manifest before activation; never downgrade a database destructively to make an
old image start. Run the ready check, tenant-negative smoke, one idempotent application replay, and
one queued-job inspection before reopening traffic.

## Backup, quota, and clean-host recovery

The nightly timer must produce an encrypted database plus private-object-manifest bundle and SHA-256
companion in OCI, retaining seven daily and four weekly points. A successful command without both
remote objects and a passing object `head` check is a failed backup. The five-minute operations timer
checks readiness, containers, quota, local disk, certificate life, and backup age; configure the
host alert channel to consume failed systemd units.

Run `deploy/production/restore_rehearsal.sh` only on a separate clean host with the age identity. The
rehearsal must validate the encrypted checksum, object inventory, database catalog, migration row,
tenant-scoped counts, and elapsed RTO. Sample owner-authorized private objects separately without
placing their content in logs or the evidence record.

When the quota guard closes, set `OCI_OBJECT_UPLOADS_ENABLED=false` and redeploy the unchanged image
pair. Keep downloads, deletion/privacy processing, applications using already-safe resume versions,
and support available. Do not delete immutable recruitment evidence, bypass scanning, or silently
move objects to a public store.

## Credential rotation

Follow `docs/CREDENTIAL_ROTATION_RUNBOOK.md`. Use overlap where the provider supports it, validate the
new credential through a bounded probe, revoke the old credential, and retain only the credential
identifier, operator, UTC time, reason, and validation result. Never retain secret values.

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

## Data-rights operation during a pause

An onboarding, upload, provider, or capacity pause must not disable correction, export, deletion,
appeal, or support intake. Verify that privacy jobs remain durable in PostgreSQL, object deletions are
idempotent, Qdrant projections are removed/rebuildable, Redis loss does not erase the request, and
retained recruitment evidence follows the approved hold rather than being silently deleted. Record
the request ID and outcome, never the exported data, in operational evidence.
