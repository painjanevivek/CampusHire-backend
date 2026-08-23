# Local Pilot HTTP Baseline — 2026-08-24

## Scope and method

This is a repeatable development baseline, not a production capacity or SLO claim. It used Uvicorn on Windows, a fresh local SQLite fixture, one synthetic institution, one published role with deterministic eligibility, one student, one administrator, 30 samples per repeated scenario, and concurrency 4. The initial application write is intentionally a single sample; the replay scenario measures the same idempotency key under concurrency.

Run `scripts/measure_pilot_http.py` against an authorized environment. Credentials are read only from process environment variables; role and resume identifiers are optional environment inputs; output defaults to the Git-ignored `.data/pilot-http-baseline.json`.

## Results

| Scenario | p50 | p95 | Max | Errors | Provisional p95 gate |
| --- | ---: | ---: | ---: | ---: | ---: |
| Live health | 3.46 ms | 6.13 ms | 7.11 ms | 0% | 250 ms |
| Student dashboard | 51.73 ms | 74.16 ms | 76.11 ms | 0% | 1,000 ms |
| Opportunity search + eligibility | 30.28 ms | 45.91 ms | 46.87 ms | 0% | 1,000 ms |
| Notification feed | 15.23 ms | 18.27 ms | 18.87 ms | 0% | 750 ms |
| Admin worker summary | 22.91 ms | 41.77 ms | 42.95 ms | 0% | 750 ms |
| Admin worker history | 26.61 ms | 65.21 ms | 69.64 ms | 0% | 1,000 ms |
| Initial application submission | 36.99 ms | 36.99 ms | 36.99 ms | 0% | 1,500 ms |
| Idempotent application replay | 28.75 ms | 64.87 ms | 65.96 ms | 0% | 1,500 ms |

All measured scenarios passed the provisional engineering gates. These wide gates detect regressions before a pilot environment exists; they are not institution-approved objectives.

## Required staging follow-up

- Repeat with PostgreSQL, Redis, Qdrant, object storage, selected scanner/parser isolation, and production-shaped network boundaries.
- Add representative role volume, concurrent institutions, bulk administrator review, worker throughput, queue age, and provider latency/cost.
- Measure cold starts, sustained traffic, saturation, error budgets, and recovery after dependency interruption.
- Obtain product/platform approval for SLOs, capacity, and cost ceilings; replace provisional gates only through a reviewed change.
