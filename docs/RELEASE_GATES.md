# CampusHire pilot and release gates

## Automated gates

- Backend lint, strict type checking, 82 passing unit/integration/security tests (one environment-gated skip), migration head, dependency consistency, and phase smoke runner pass on the 2026-08-24 local candidate.
- Frontend lint, strict type checking, 70 passing tests, production build, zero dependency vulnerabilities, public-route smoke, and the 126-check Chromium/Firefox/WebKit rendered accessibility matrix pass on the 2026-08-24 local candidate.
- Core profiles, resumes, drives, applications, deterministic eligibility, and notifications do not require Gemini.

## Performance and cost gate

The local concurrency-20 baseline and proposed capacity/alert envelope are recorded in `docs/PERFORMANCE_BASELINE_2026-08-24.md` and `docs/PILOT_CAPACITY_PROPOSAL.md`. They are not production SLOs. Release requires approved pilot size, provider rates, cost ceiling, managed HTTPS repetition, and named SLO/alert owners. Every report must retain environment, dataset, concurrency, percentile, failures, and date.

## Human gates that cannot be automated or self-certified

- TNP sandbox review of drive, rule, override, and explanation wording.
- Consented student usability and accessibility pilot.
- One-drive shadow comparison against the institution’s current authoritative process.
- Named institution approval for privacy notice, retention, support, appeal, and incident ownership.
- Production backup restoration in the target hosting environment.
- Managed reproduction of the locally proven credential-free PDF parser sandbox with CPU, memory, wall-time, read-only input, no-network, and bounded-output controls. ClamAV and a separate worker alone do not satisfy this gate.

Until these human gates are signed, the system is code-complete for an internal fictional-data pilot, not approved for real student production data.

Generate the candidate evidence with `scripts/build_release_candidate_manifest.py --strict`. A nonzero exit is an intentional no-go signal; never bypass it without closing or formally evidencing every reported gate.
