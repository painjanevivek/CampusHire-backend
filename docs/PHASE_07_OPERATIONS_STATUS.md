# Phase 07 operations qualification status

Status: **engineering controls implemented; external production gate pending**.

## Candidate controls implemented in source

- Backend and Frontend images carry the full Git revision, build timestamp, and reviewed OpenAPI SHA-256 as OCI labels. Production deployment compares those labels with protected candidate values after pulling immutable digests.
- Email delivery remains an explicit `manual` or `smtp` choice. Manual mode requires an approved handoff reference and never reports an email as delivered.
- Scheduled checks cover readiness, container health, object-upload capacity, local disk, certificate lifetime, encrypted recovery-point age, oldest queued work, and expired worker leases.
- Failed backup or operations-check units invoke a minimal HTTPS webhook event tied to a protected owner reference.
- Encrypted recovery bundles now include the PostgreSQL dump and checksum-verified private-object bytes. A rehearsal restores the database into an ephemeral PostgreSQL container and the objects into a distinct rehearsal bucket/prefix.

## Evidence still required on the selected host

- Build and publish the exact digest-qualified images with non-placeholder labels.
- Deploy to an isolated synthetic staging host and prove a named operator receives a test alert.
- Run the restore rehearsal on a separate clean host and record measured database/object recovery time against approved RPO/RTO.
- Rehearse secret rotation, provider outage, worker failure, migration failure, rollback, and recovery.
- Run the documented synthetic fixture and 50-concurrent-session workload; record host shape, p50/p95/p99, errors, worker throughput, and actual monthly infrastructure/AI cost.

No host measurements or external approvals are present in this repository. Phase 07 therefore does not authorize real student data, claim high availability, or close the release `NO-GO`.
