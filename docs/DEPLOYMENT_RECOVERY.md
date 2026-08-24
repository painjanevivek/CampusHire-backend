# Deployment, Rollback, and Recovery

## Release sequence

1. Pin immutable frontend and backend commit SHAs and record the OpenAPI snapshot.
2. Pause background workers before any schema change that is not backward-compatible.
3. Back up PostgreSQL, Qdrant metadata, and object-store version manifests. Verify that the backup is readable before continuing.
4. Run `python -m alembic upgrade head`, start the backend, then check `/api/v1/health/live` and `/api/v1/health/ready`.
5. Start one worker and verify lease acquisition, heartbeat, terminal state, and an append-only job event.
6. Deploy the frontend, verify security headers, sign-in, readiness, opportunities, resume, roadmap, privacy, and administrator operations.
7. Resume the full worker pool only after both deployables pass smoke checks.

## Application rollback

Roll back to the previous immutable image when a release fails smoke checks. Do not downgrade the database merely to match an application image. The previous application must remain compatible with additive migrations during the release window. If a migration is incompatible, pause traffic and workers, follow the migration-specific downgrade procedure, and preserve a fresh backup first.

## Database rehearsal

From `Backend/`, run:

```powershell
.\scripts\rehearse_postgres_recovery.ps1
```

The script starts a uniquely named, ephemeral, digest-pinned PostgreSQL 17 container; migrates from base to head; downgrades one revision; rolls forward; seeds synthetic authoritative records; performs a custom-format logical backup; and restores into a second database. It verifies the migration head, record counts, immutable application snapshots, audit history, queued-work timestamp, and private-object reference. Evidence is written below `.data/` and contains no credentials.

On the selected shared-VM staging host, upload and run the executable
`scripts/rehearse_shared_vm_recovery.sh` as the dedicated deployment user. It
refuses unexpected database names, restores only into
`campushire_restore_rehearsal`, verifies both databases before cleanup, and
never downgrades the active database. See
`docs/SHARED_VM_RECOVERY_EVIDENCE_2026-08-25.md` for the sanitized timed result.

## Dependency-failure rehearsal

With the approved parser image built, run:

```powershell
.\.venv\Scripts\python.exe scripts\rehearse_dependency_failures.py `
  --parser-image campushire-pdf-parser:test
```

The bounded local matrix exercises Redis fail-closed behavior, worker lease recovery, exhausted jobs, application and notification idempotency, scanner and private-storage retries, Gemini degradation, parser timeout cleanup, and continued core operation without Gemini or Qdrant. The machine record is written below `.data/`; repeat the same operator paths on selected managed services before release.

Run `scripts/rehearse_shared_vm_dependencies.sh` on the shared-VM staging host
to repeat bounded PostgreSQL, Redis, Qdrant, ClamAV, and worker outages. Its
exit trap restarts only CampusHire services; it never stops the shared gateway
or unrelated workloads. The complete local matrix remains the source for
synthetic timeout, exhausted-retry, and private-storage fault injection.

## Incident boundaries

- Stop uploads and workers for parser, malware scanner, or object-store incidents.
- Disable semantic matching independently when Gemini or Qdrant is unsafe; deterministic eligibility remains available.
- Rebuild Qdrant only from reviewed PostgreSQL facts and versioned embedding metadata.
- Restore private objects only alongside ownership metadata; never expose a bucket or recovery export directly.
- Record operator, timestamp, correlation ID, affected institution, and validation result for every recovery action.

## Exit criteria

Release only when the migration head, restored authoritative evidence, worker lifecycle, frontend production build, API contract, security gates, and documented pilot limitations all pass. Shared-VM restore and bounded dependency evidence now pass for synthetic staging. Representative UAT, governance review conditions, approved operational budgets, and the separate deferred Deep Security Scans remain explicit real-data release gates.
