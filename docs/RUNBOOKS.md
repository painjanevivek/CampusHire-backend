# CampusHire operational runbooks

## Login outage

Check PostgreSQL and Redis readiness, then authentication error rate. Do not weaken CSRF, cookie, or rate-limit controls. If Redis is unavailable in production, authentication fails closed while existing health diagnostics remain available.

## AI provider outage

Open the AI circuit breaker, stop retry storms, and surface queued or failed status. Profiles, drives, applications, deterministic eligibility, and existing notifications remain available. Re-run only idempotent jobs after recovery.

## Queue backlog

Inspect the oldest job, failure code, and deduplication key. Scale workers only after identifying the slow dependency. Never replay a job without its idempotency key.

## Database issue and restore

Stop writes, capture the incident timestamp, restore the latest verified PostgreSQL backup into a clean environment, run migrations, validate row counts and authorization boundaries, then rehearse forward recovery before reopening writes.

## Policy or matching incident

Disable the affected institution feature flag, preserve rule, prompt, and model versions and audit evidence, notify the named TNP owner, and revert to deterministic rules and manual review. Do not silently recalculate historical decisions.
