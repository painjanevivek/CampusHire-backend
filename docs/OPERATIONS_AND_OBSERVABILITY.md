# Operations and Observability

## Worker contract

Run the API and resume worker as separately supervised processes. The worker command is:

```text
python -m app.worker
```

PostgreSQL remains authoritative for queue order, attempts, leases, cancellation, and terminal state. A claim records a random process identity and bounded lease. Each storage or scanner boundary refreshes the heartbeat. An expired lease is either requeued, cancelled, or terminally failed when its retry budget is exhausted. Retrying never creates another resume version.

Use `RESUME_WORKER_LEASE_SECONDS` to set the lease between 30 and 3,600 seconds. It must exceed the configured malware scanner timeout. Stop a worker gracefully during deployment; stale lease recovery protects jobs after abrupt termination.

## Operator controls

Institution administrators can inspect their own tenant only:

- `GET /api/v1/admin/operations/summary`
- `GET /api/v1/admin/operations/resume-jobs`
- `POST /api/v1/admin/operations/resume-jobs/{job_id}/cancel`
- `POST /api/v1/admin/operations/resume-jobs/{job_id}/retry`

State changes require session-bound CSRF and append both an audit event and a PII-minimized job event. Cross-institution identifiers return not found.

## Telemetry boundary

API logs include event name, correlation ID, HTTP method, route, status, and duration. Worker logs include random worker identity, job UUID, and safe event codes. Unknown log extras are ignored; email, bearer credentials, and common secret assignments are redacted. Resume content, filenames, contact data, vectors, and provider prompts are never logged.

The reviewed semantic scoring fixture is versioned at `tests/fixtures/semantic-match-evaluation-v1.json`. Run `python scripts/evaluate_matching.py`; CI fails unless every bounded case remains inside its approved score range. This evidence evaluates presentation relevance only and makes no hiring or eligibility claim.
