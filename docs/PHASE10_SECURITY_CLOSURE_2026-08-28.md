# Phase 10 Backend Security Closure — 2026-08-28

Outcome: **fixed**. Deep Scan `b3b6a923-43ef-4bb6-ac3e-1b8200b1a8cc` completed against backend revision `707a0d4fd4e1eb91b5ef4e57b0cbd7ef8e27ce2e`. The scan, independent boundary investigation, and one bypass/regression review found no critical issue and left no validated high issue after remediation.

## Closed paths and preserved behavior

- MFA replacement now requires a recently verified enrolled factor and keeps the active secret usable until a separately stored pending secret is confirmed. First-time administrator enrollment remains available from the password-authenticated setup session.
- MFA confirmation/challenge failures consume an enrollment-level budget shared across newly created sessions, while valid TOTP and one-time recovery-code challenges continue to work.
- Roster responses no longer expose invitation capabilities. Resend requires recent MFA, rotates the token, and queues an absolute frontend activation URL.
- Request logs use route templates, Uvicorn/Caddy duplicate access logging is disabled, sensitive email variables are encrypted while deliverable and purged after delivery/terminal failure, and the migration safely fails legacy queued capability mail while clearing historical plaintext variables.
- SMTP STARTTLS uses a hostname-verifying system trust context. Upload bodies are bounded before multipart parsing. Proxy client identity is accepted only from the configured trusted gateway, with an account limiter retained for authentication.
- Account deletion requires the explicit account-wide scope and explains that every institution membership is affected. Inactive administrators/institutions fail closed.
- Audit export retains tenant/permission/filter/formula-injection controls while streaming the complete result in bounded database batches.
- Release workflows now pin every third-party action to a full commit SHA.

## Regression evidence

- Focused security tests: `40 passed`.
- Complete backend suite: `120 passed, 1 skipped`.
- `ruff check .`: passed.
- strict `mypy app`: passed for 95 source files.
- `pip check`: no broken requirements.
- phase smoke: phases 0–13 passed; semantic-match evaluation: 4/4 passed.
- OpenAPI snapshot regenerated; migration head: `20260828_0015`.
- Fresh SQLite rehearsal was not treated as migration evidence because earlier PostgreSQL-oriented migrations intentionally use constraint operations unsupported by SQLite. Docker was unavailable locally; the pinned CI PostgreSQL upgrade/downgrade/upgrade gate is the authoritative dialect rehearsal after push.

The original issues no longer reproduce in focused tests: an invalid replacement cannot displace the active MFA secret, guesses remain locked across fresh sessions, sensitive capabilities are absent from roster responses/log paths/durable terminal email payloads, over-limit uploads are rejected at the request boundary, cross-tenant and inactive-state access remains denied, and exports exceed 100 rows without whole-result buffering. Legitimate enrollment, sign-in, email retry, account-wide deletion, audit filtering/export, and application workflows remain green in the full suite.

Real-data launch remains **NO-GO** until the named human UAT, privacy/legal, operational-ownership, provider-recovery/capacity, immutable artifact, and final authorization gates are signed.
