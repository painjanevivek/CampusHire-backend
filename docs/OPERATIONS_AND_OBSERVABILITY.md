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

## Provisional alert thresholds

Until managed staging replaces them with approved service objectives, alert when critical-route error rate reaches 1% for five minutes, dashboard/opportunity p95 exceeds 1,000 ms, ordinary-read p95 exceeds 750 ms, or application-write p95 exceeds 1,500 ms. Warn on queue age above 120 seconds and page above 600 seconds. Warn at 70% database-pool utilization and page at 90%; correlate this with request concurrency before scaling. Treat a parser/scanner OOM, terminal cleanup failure, cross-tenant denial failure, or duplicate business effect as immediately release-blocking.

The local baseline shows ClamAV is the dominant memory consumer. Allocate and monitor it independently from API/worker resources, and never bypass malware scanning to recover capacity.
