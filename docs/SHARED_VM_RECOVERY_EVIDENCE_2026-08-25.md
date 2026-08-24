# Shared-VM Recovery Evidence — 2026-08-25

## PostgreSQL restore and migration recovery

`scripts/rehearse_shared_vm_recovery.sh` created the exact isolated database
`campushire_restore_rehearsal`; it never changed the active `campushire`
database. The operator produced a custom-format logical backup, restored it,
compared the Alembic head and authoritative counts, downgraded one revision,
upgraded to head, repeated the comparisons, and removed the isolated database
and temporary backup.

| Measurement | Observed result |
| --- | --- |
| Backup | 698 ms |
| Restore and initial verification | 1,776 ms |
| Rollback and roll-forward | 6,967 ms |
| Total rehearsal | 9,441 ms |
| Migration | `20260824_0010` → `20260824_0009` → `20260824_0010` |
| Snapshot digest | `94729bcebc48ab48491bedcc48710382d0f0796e4d34a523584a7cc5b184ff86` |

Matched counts were 5 users, 3 institutions, 1 application, 25 audit events,
12 resume-processing jobs, and 60 resume-job events. The active database was
rechecked after forward recovery and remained unchanged. This measures a
synthetic snapshot restore; it is not an institutional RTO/RPO commitment.

## Controlled dependency failures

`scripts/rehearse_shared_vm_dependencies.sh` stopped only CampusHire services
and guaranteed restart on exit.

| Failure | During outage | Recovery evidence |
| --- | --- | --- |
| PostgreSQL | liveness `200`, readiness `503` | readiness returned `200` |
| Redis | sign-in failed closed with `503` | invalid sign-in returned normal `401` |
| Qdrant | liveness/readiness stayed `200` | vector service restarted |
| ClamAV | API liveness stayed `200` | scanner returned healthy |
| Worker | API liveness stayed `200` | worker restarted through ordered dependencies |

The performance rehearsal separately completed three uploaded PDFs through
private storage, ClamAV, durable jobs, and the rootless parser. Application
replay produced 60 successful idempotent responses with no duplicate effect;
Gemini/Qdrant-unavailable matching returned a safe, successful degraded result.
The exhaustive synthetic parser-timeout, stale-lease, storage, quota, and retry
matrix remains covered by the local Phase 7D rehearsal; this shared-VM run adds
selected-host recovery evidence without claiming third-party managed-vendor
behavior.
