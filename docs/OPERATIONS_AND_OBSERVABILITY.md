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

The bounded OCI production topology, off-host encrypted backup controls, quota stop conditions,
credential rotation, availability objective, and paid-upgrade triggers are maintained in
`docs/FREE_FIRST_PRODUCTION_OPERATIONS.md`.

## Production signal ownership

| Signal | Authoritative source | Collection / alert boundary |
| --- | --- | --- |
| API status, route template, duration, correlation ID | Redacted backend JSON logs | External log/metric collector computes error rate and p50/p95/p99 without query strings or bodies |
| API readiness | `/api/v1/health/ready` plus PostgreSQL probe | Five-minute `campushire-operations-check` and external availability probe |
| Container/process state | Docker state and declared health checks | Five-minute operations check; failed systemd unit must page the Platform/SRE owner |
| Queue age and worker leases | PostgreSQL background-job records | Approved monitoring query/export; Redis is never the authoritative queue source |
| Database pool | SQLAlchemy/driver pool telemetry | Approved monitoring export; page at 90% and investigate concurrency before resizing |
| CPU and memory | OCI/host metrics by service where available | Alert only after three consecutive five-minute threshold windows |
| Local disk | Dedicated host filesystem | Operations check closes at 70%; do not delete evidence to regain space |
| Private object allocation | OCI Object Storage inventory and configured 14 GB upload guard | Deployment/upload guard plus signed monitoring export |
| Backup age | Newest encrypted `.age` recovery bundle in the private OCI bucket | Operations check blocks at 30 hours |
| Certificate life | Owned production endpoint certificate | Operations check blocks inside 14 days |
| Email allowance, bounce, complaint | OCI Email Delivery metrics/suppression list and outbox evidence | Stop optional messages before quota; security/account messages retain priority |

The signed activation snapshot binds the exact candidate and controlled monitoring reference. The
repository does not contain an OCI alarm destination or named on-call person; those remain external
production gates and blank owner fields must not be interpreted as configured monitoring.
