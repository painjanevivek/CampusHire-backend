# Shared-VM Performance Evidence — 2026-08-25

## Test profile

The immutable HTTPS staging release was exercised with synthetic `example.com`
accounts, 20 samples, three rounds, and concurrency 10. Credentials were
randomly rotated for the run and discarded. The raw machine report is retained
under ignored `.data/`; this document contains only sanitized results. Budgets
are provisional engineering gates until the product/platform owner approves
the pilot envelope.

| Scenario | p95 | Budget | Errors |
| --- | ---: | ---: | ---: |
| Liveness | 79.16 ms | 250 ms | 0% |
| Student dashboard | 661.29 ms | 1,000 ms | 0% |
| Student profile | 281.83 ms | 750 ms | 0% |
| Resume versions | 444.64 ms | 750 ms | 0% |
| Opportunities with eligibility | 449.18 ms | 1,000 ms | 0% |
| Notifications | 498.68 ms | 750 ms | 0% |
| Admin worker summary | 478.81 ms | 750 ms | 0% |
| Admin worker history | 529.38 ms | 1,000 ms | 0% |
| Admin application list | 397.56 ms | 1,000 ms | 0% |
| Application submission | 56.84 ms | 1,500 ms | 0% |
| Idempotent application replay | 423.90 ms | 1,500 ms | 0% |
| Provider-degraded semantic match | 66.21 ms | 1,500 ms | 0% |

All scenarios passed. Three real synthetic resume uploads completed in 7.66 s
at 0.392 jobs/s; job p50 was 1.843 s and p95 was 2.171 s. All reached the
expected `review_required` terminal state, proving scanner/parser/worker
completion rather than HTTP acceptance alone.

## Capacity observation

The post-test snapshot showed 43.7 GiB VM memory available and 192.0 GiB disk
available. CampusHire container memory ranged from 5.4 MiB (Redis) to 956.2 MiB
(ClamAV); API used 166.3 MiB, frontend 64.2 MiB, worker 48.0 MiB, PostgreSQL
30.5 MiB, and Qdrant 18.9 MiB. PostgreSQL showed one active and six idle
connections. These are post-run observations, not peak telemetry or an HA
capacity claim. No paid AI provider was invoked in degraded mode.

The measured candidate meets the provisional concurrency-10 staging envelope.
Pilot concurrency, upload volume, availability target, provider pricing, and
cost ceiling still require explicit owner approval before becoming SLOs.
