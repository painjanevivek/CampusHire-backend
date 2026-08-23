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

The script starts a uniquely named, ephemeral PostgreSQL 16 container; migrates from base to head; downgrades one revision; rolls forward; performs a custom-format logical backup; restores into a second database; and verifies the migration head plus a recovery marker. Evidence is written to `.data/release-rehearsal.json` and contains no credentials.

## Incident boundaries

- Stop uploads and workers for parser, malware scanner, or object-store incidents.
- Disable semantic matching independently when Gemini or Qdrant is unsafe; deterministic eligibility remains available.
- Rebuild Qdrant only from reviewed PostgreSQL facts and versioned embedding metadata.
- Restore private objects only alongside ownership metadata; never expose a bucket or recovery export directly.
- Record operator, timestamp, correlation ID, affected institution, and validation result for every recovery action.

## Exit criteria

Release only when the migration head, restored probe, worker lifecycle, frontend production build, API contract, security gates, and documented pilot limitations all pass. Human UAT, institutional privacy approval, isolated PDF parsing, and the separate Deep Security Scans remain explicit external release gates.
