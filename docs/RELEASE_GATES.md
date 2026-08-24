# CampusHire pilot and release gates

## Automated gates

- Backend lint, strict type checking, 88 passing unit/integration/security tests (one environment-gated skip), migration head, dependency consistency, and shared-VM operator scripts pass on the 2026-08-25 candidate.
- Frontend lint, strict type checking, 70 passing tests, production build, zero dependency vulnerabilities, public-route smoke, and the 126-check Chromium/Firefox/WebKit rendered accessibility matrix pass on the 2026-08-24 local candidate.
- Core profiles, resumes, drives, applications, deterministic eligibility, and notifications do not require Gemini.

## Performance and cost gate

The shared-VM HTTPS concurrency-10 baseline passes with zero HTTP errors and
three completed resume jobs; see
`docs/SHARED_VM_PERFORMANCE_EVIDENCE_2026-08-25.md`. These remain engineering
budgets, not production SLOs. Real-data release requires approved pilot size,
provider rates, cost ceiling, availability target, and named SLO/alert owners.

## Human gates that cannot be automated or self-certified

- TNP sandbox review of drive, rule, override, and explanation wording.
- Consented student usability and accessibility pilot.
- One-drive shadow comparison against the institution’s current authoritative process.
- Named institution approval for privacy notice, retention, support, appeal, and incident ownership.
- Explicit owner approval of the shared-VM recovery result and proposed pilot
  performance/cost envelope.
- A repeat recovery/parser/failure rehearsal before any future hosting-provider
  migration; the selected shared-VM launcher already reproduces the required
  credential-free parser controls.

Until these human gates are signed, the deployed system is approved only for
synthetic staging, not real student production data.

Generate the candidate evidence with `scripts/build_release_candidate_manifest.py --strict`. A nonzero exit is an intentional no-go signal; never bypass it without closing or formally evidencing every reported gate.
