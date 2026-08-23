# PostgreSQL Recovery Rehearsal — 2026-08-24

## Scope

This is development evidence from an isolated `postgres:16-alpine` container, not a staging or production recovery claim. The rehearsal used the committed Alembic chain through `20260824_0010`; no persistent Docker volume, credential, user data, or production service was touched.

## Results

| Check | Result | Elapsed |
| --- | --- | ---: |
| Base-to-head migration | `20260824_0010` | 3,954 ms |
| Downgrade one revision | `20260824_0009` | 1,077 ms |
| Roll forward to head | `20260824_0010` | 1,095 ms |
| Custom-format logical backup | Passed | 295 ms |
| Restore into a second database | Passed | 1,028 ms |
| Restored public tables | 30 | — |
| Migration head preserved | Passed | — |
| Recovery probe preserved | `campushire-phase6` | — |

The generated machine-readable record is `.data/release-rehearsal.json` and is intentionally excluded from Git. Reproduce it with `scripts/rehearse_postgres_recovery.ps1`.

## Interpretation

The migration chain supports a one-revision rollback and subsequent roll-forward on PostgreSQL 16. The logical backup restored both the Alembic head and a source marker into a distinct database. These timings establish a local lower-bound measurement only; they are not RTO/RPO commitments.

## Remaining release evidence

- Repeat against a representative staging snapshot and selected managed PostgreSQL service.
- Time object-store manifest recovery and Qdrant rebuild from reviewed PostgreSQL facts.
- Exercise Redis outage/return and worker drain/resume in the staging topology.
- Record institution-approved RTO/RPO, incident contacts, and authorization for destructive recovery actions.
