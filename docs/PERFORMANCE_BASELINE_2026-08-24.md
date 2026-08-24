# Local Performance and Capacity Baseline — 2026-08-24

## Scope and method

This is synthetic local evidence, not managed-staging capacity or an approved SLO. `scripts/rehearse_performance.ps1` created ephemeral pinned PostgreSQL 17, authenticated Redis 8, and ClamAV services; migrated a clean database; seeded one synthetic institution; started the API and one real worker; used the credential-free parser image; and removed every started process/container after capture. Gemini and Qdrant were intentionally unavailable.

The peak pass used 50 samples × 3 rounds for each repeated HTTP scenario, concurrency 20, one Uvicorn process, and ten distinct PDF jobs. Machine evidence is written below `.data/` and excluded from Git.

## Peak-pass results

| Scenario | p50 | p95 | p99 | Throughput | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Live health | 27.81 ms | 69.47 ms | 84.36 ms | 547.93 rps | 0% |
| Student dashboard | 407.60 ms | 819.98 ms | 1,093.39 ms | 44.35 rps | 0% |
| Student profile | 155.39 ms | 453.62 ms | 549.72 ms | 87.65 rps | 0% |
| Resume versions | 180.39 ms | 403.22 ms | 416.13 ms | 82.84 rps | 0% |
| Opportunity search + eligibility | 224.31 ms | 474.87 ms | 526.66 ms | 72.77 rps | 0% |
| Notification feed | 116.08 ms | 321.78 ms | 373.10 ms | 111.86 rps | 0% |
| Admin worker summary | 178.00 ms | 466.70 ms | 517.95 ms | 79.66 rps | 0% |
| Admin worker history | 180.52 ms | 432.27 ms | 449.84 ms | 81.84 rps | 0% |
| Admin application list | 168.69 ms | 529.21 ms | 538.04 ms | 78.29 rps | 0% |
| Initial application write | 89.35 ms | 89.35 ms | 89.35 ms | single write | 0% |
| Concurrent idempotent replay | 205.86 ms | 670.87 ms | 716.31 ms | 61.49 rps | 0% |
| Degraded semantic match | 30.63 ms | 37.06 ms | 37.29 ms | 57.65 rps | 0% |

Ten of ten resume jobs reached `review_required` through ClamAV and the isolated parser. End-to-end throughput was 0.76 jobs/second; job p50 was 1,266.5 ms and p95 was 1,451.3 ms.

## Resource observations

The post-run snapshot showed seven PostgreSQL connections (one active), PostgreSQL at 58.47 MiB, Redis at 5.84 MiB, and ClamAV at 1.054 GiB. Database rollback counters include normal read-only session cleanup and are not an HTTP error count. ClamAV dominates the local memory footprint and should receive an explicit managed memory budget.

## Interpretation

All provisional engineering gates passed with zero request errors. Dashboard p95 used 82% of its one-second gate at concurrency 20, so 20 is a burst validation point rather than the proposed sustained pilot level. The first run exposed an invalid synthetic rule fixture; the fixture was corrected to include the required explainability label, and both the normal and peak workloads then passed.

Repeat the exact harness over managed HTTPS with deployment metrics, representative multi-tenant volumes, cold starts, provider pricing/duration, and approved SLOs before describing this as production capacity.
