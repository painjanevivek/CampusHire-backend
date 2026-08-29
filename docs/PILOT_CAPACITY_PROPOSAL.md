# Pilot Capacity and Cost Proposal

These are conservative pre-approval defaults derived from local synthetic evidence. Product and platform owners must replace or approve them before a real-data pilot.

## Proposed pilot envelope

| Dimension | Proposed initial value |
| --- | ---: |
| Registered students | 500 |
| Administrators | 10 |
| Sustained concurrent requests | 12 |
| Short burst concurrency | 20 |
| Resume uploads | 1,000/month; 10 in five minutes |
| Semantic match requests | 10,000/month |
| Availability objective | 99.0% monthly, excluding announced maintenance |
| Cost ceiling | USD 300/month, pending provider-rate completion |

The local peak pass exercised concurrency 20 and ten sequential worker jobs. It provides regression headroom for the proposed sustained level but does not model public network latency, managed database limits, multi-instance coordination, or provider quotas.

## Provisional service budgets

- Health p95 ≤ 250 ms; ordinary authenticated reads p95 ≤ 750 ms.
- Complex dashboard/opportunity/admin lists p95 ≤ 1,000 ms.
- Application and bounded AI-assisted writes p95 ≤ 1,500 ms.
- Critical HTTP p99 ≤ 2,000 ms and error rate < 1% over five minutes.
- Worker p95 ≤ 5 seconds, oldest queued work warning at 120 seconds and critical at 600 seconds.
- Database pool warning at 70% and critical at 90% of configured capacity for five minutes.
- ClamAV memory warning at 1.5 GiB and critical at its deployment limit; any OOM blocks uploads.

## Cost model

Run `python scripts/estimate_pilot_cost.py` with reviewed provider rates. The default demand model yields 1,000 monthly uploads, 0.977 GiB newly retained resume data, 10,000 semantic requests, and 25 million embedding-input tokens. The committed defaults intentionally leave variable provider unit rates at zero and return `pricing_complete: false`; the USD 200 fixed-infrastructure placeholder and USD 300 ceiling are proposals, not a procurement claim.

Approval must identify the rate-card source/date, retention multiplier, taxes/egress, monitoring,
backups, headroom, and owner for quota alerts. The dedicated OCI pilot uses the documented 99.0%
availability objective, 24-hour RPO, and four-hour RTO; the earlier 99.5% figure is superseded.
Use `docs/MANAGED_PILOT_REHEARSAL_RECORD.md` for the managed-environment execution evidence and
Vivek's final capacity/cost authorization.
