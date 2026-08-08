# CampusHire pilot and release gates

## Automated gates

- Backend lint, strict type checking, 30+ unit/integration/security tests, migration head, dependency consistency, and phase smoke runner pass.
- Frontend lint, strict type checking, unit tests, production build, dependency audit, and desktop/mobile browser smoke matrix pass.
- Core profiles, resumes, drives, applications, deterministic eligibility, and notifications do not require Gemini.

## Performance targets for the pilot environment

- Non-AI API: p95 below 400 ms at 50 concurrent users with the fictional pilot dataset.
- Application submission: p99 below 1 second with 100 concurrent submissions and zero duplicates.
- Opportunity search: p95 below 600 ms over 10,000 students and 500 roles.
- AI job acknowledgement: below 1 second; completion measured separately by workflow and model.
- Every load report must record environment, dataset, concurrency, percentile, failures, and date.

## Human gates that cannot be automated or self-certified

- TNP sandbox review of drive, rule, override, and explanation wording.
- Consented student usability and accessibility pilot.
- One-drive shadow comparison against the institution’s current authoritative process.
- Named institution approval for privacy notice, retention, support, appeal, and incident ownership.
- Production backup restoration in the target hosting environment.

Until these human gates are signed, the system is code-complete for an internal fictional-data pilot, not approved for real student production data.
