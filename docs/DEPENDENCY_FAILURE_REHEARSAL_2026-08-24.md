# Dependency-Failure Rehearsal — 2026-08-24

## Scope

This is bounded local evidence using synthetic fixtures, controlled unavailable adapters, and the approved local parser image. It does not claim selected managed vendors or production networks were tested. The machine-readable record is `.data/dependency-failure-rehearsal-phase7d.json` and is intentionally excluded from Git.

## Results

| Scenario | Expected behavior | Result | Elapsed |
| --- | --- | --- | ---: |
| Redis unavailable | Protected expensive operation fails closed | Passed | 3,867 ms |
| Worker termination / stale lease | Durable work is recovered within its attempt budget | Passed | 3,842 ms |
| Exhausted stale job | Job becomes inspectable terminal failure | Passed | 1,477 ms |
| Application replay | Same idempotency key creates no duplicate application | Passed | 4,079 ms |
| Notification retry | Duplicate delivery is suppressed | Passed | 1,188 ms |
| ClamAV unavailable | Job retries without losing authoritative state | Passed | 3,921 ms |
| Private storage unavailable | Cleanup remains durable and retries | Passed | 1,515 ms |
| Storage retries exhausted | Safe terminal state is recorded | Passed | 1,592 ms |
| Gemini unavailable | Semantic match degrades without affecting eligibility | Passed | 2,032 ms |
| Parser timeout | Bounded runtime terminates and removes artifacts | Passed | 2,156 ms |
| Gemini and Qdrant absent | Core CRUD, deterministic eligibility, and phase smoke continue | Passed | 2,868 ms |

Parser inspection additionally confirmed no network, no credentials, non-root execution, read-only root, dropped capabilities, `no-new-privileges`, and timeout cleanup.

## Operator interpretation

The controlled paths fail closed or degrade safely, durable work remains recoverable, and replay checks prevent duplicate business effects. PostgreSQL recovery separately measured a 302-second synthetic oldest-queue age after restore. These observations are neither RTO/RPO commitments nor managed-service availability evidence.

Before a pilot, repeat every scenario against selected managed staging services, record provider request IDs and queue metrics without student content, and obtain platform-owner acceptance for recovery budgets.
