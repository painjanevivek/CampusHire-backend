# Managed Pilot Recovery, Capacity, and Cost Record

Status: **Pending dedicated-OCI execution and Vivek's approval.** Record sanitized measurements
and controlled evidence references only. This file is an execution form, not proof that a rehearsal
has occurred.

## Preconditions

- The dedicated OCI host attestation, private bucket, private networking, protected secrets, and
  digest-pinned candidate pass the production environment validator.
- The candidate and rollback archives, SBOM/provenance/signature references, and strict release
  manifest identify the same source and registry digests.
- The rehearsal target is clean and isolated. It must never point at the live database or reuse
  production credentials beyond the off-host age identity supplied by an authorized operator.

## Recovery rehearsal

| Check | Required result | Controlled evidence reference |
| --- | --- | --- |
| Backup freshness | Newest encrypted recovery point is less than 24 hours old | Pending |
| Checksum and decrypt | SHA-256 verification and age decryption pass | Pending |
| Isolated PostgreSQL restore | Restore completes on a clean target and migration record is present | Pending |
| Restore-point objective | Data selected is within the 24-hour RPO | Pending |
| Recovery-time objective | Full exercise completes within the four-hour RTO | Pending |
| Rollback/forward pair | Exact rollback and forward digests pass smoke checks | Pending |
| Dependency failures | Redis, Qdrant, ClamAV, worker, parser, and object-storage failures remain bounded | Pending |

## Capacity and alert rehearsal

Run production-like synthetic load at the chartered ceiling: 12 sustained and 20 burst concurrent
requests, 1,000 monthly-upload model, and at least the existing zero-error concurrency minimum.

| Signal | Approval threshold | Controlled evidence reference |
| --- | --- | --- |
| Availability objective | 99.0% monthly, excluding announced maintenance | Pending |
| Ordinary-read p95 | 750 ms or less | Pending |
| Dashboard/opportunity p95 | 1,000 ms or less | Pending |
| Application/write p95 | 1,500 ms or less | Pending |
| HTTP errors | Below 1% for each five-minute measurement window | Pending |
| CPU / memory | Alert at 70% / 75% for three consecutive windows | Pending |
| Disk / private object allocation | Alert at 70% for three consecutive windows | Pending |
| Database pool / worker health | Page at 90% pool use or two missed lease periods | Pending |
| Backup / certificate | Page at backup age 30 hours or certificate expiry 14 days | Pending |

Any threshold failure pauses new-institution onboarding and keeps the release `NO-GO` until the
root cause, remediation, and independent retest are recorded.

## Cost authorization

The operator attaches the provider rate-card source/date, taxes, egress, monitoring, backup,
retention multiplier, capacity headroom, and named quota-alert owner. Vivek records one of
`approve`, `approve with time-bounded conditions`, or `reject` for the USD 300/month ceiling,
99.0% availability objective, RPO/RTO, and pilot envelope. A missing, rejected, or expired
decision is a release blocker.
