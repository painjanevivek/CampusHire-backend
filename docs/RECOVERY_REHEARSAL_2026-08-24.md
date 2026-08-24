# PostgreSQL Recovery Rehearsal — 2026-08-24

## Scope

This is development evidence from an isolated, digest-pinned PostgreSQL 17 container, not a managed staging or production recovery claim. The rehearsal used synthetic data and the committed Alembic chain through `20260824_0010`; no persistent Docker volume, retained credential, user data, or production service was touched.

## Results

| Check | Result | Elapsed |
| --- | --- | ---: |
| Base-to-head migration | `20260824_0010` | 1,321 ms |
| Downgrade one revision | `20260824_0009` | 902 ms |
| Roll forward to head | `20260824_0010` | 804 ms |
| Custom-format logical backup | Passed | 251 ms |
| Restore into a second database | Passed | 483 ms |
| Restored public tables | 30 | — |
| Migration head preserved | Passed | — |
| Recovery probe preserved | `campushire-phase7d` | — |
| Authoritative row counts preserved | 1 institution, 2 users, 1 profile, 1 resume, 1 queued job, 1 application, 1 audit event | — |
| Immutable application snapshots preserved | Passed | — |
| Private-object reference preserved | Passed | — |
| Oldest queued work measured after restore | 302 seconds | — |

The generated machine-readable record is `.data/release-rehearsal-phase7d.json` and is intentionally excluded from Git. Reproduce it with `scripts/rehearse_postgres_recovery.ps1`.

## Interpretation

The migration chain supports a one-revision rollback and subsequent roll-forward on PostgreSQL 17. The logical backup restored the Alembic head, source marker, authoritative counts, immutable decision inputs, audit history, queued work, and opaque private-object reference into a distinct database. These timings are local synthetic observations, not an availability claim or RTO/RPO commitment.

## Remaining release evidence

- Repeat against a representative staging snapshot and selected managed PostgreSQL service.
- Time object-store manifest recovery and Qdrant rebuild from reviewed PostgreSQL facts on selected providers.
- Repeat the dependency-failure matrix against managed Redis, scanner, storage, worker, parser, and AI services.
- Record institution-approved RTO/RPO, incident contacts, and authorization for destructive recovery actions.
