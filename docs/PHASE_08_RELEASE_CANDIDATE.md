# Phase 08 Backend release-candidate record

**Status:** Engineering validation is complete for the source pair below. The release remains
**synthetic-only / NO-GO for real student data and production** pending institutional policy,
external review, deployment, and final authorization.

## Candidate identity

| Item | Value |
| --- | --- |
| Backend branch | `phase/08-release-candidate` |
| Frontend branch | `feat/landing-and-sign-in-experience` |
| Backend source commit | `532dd83056a95d0769b5d2f4991128688e921bd1` |
| Frontend source commit | `533fd4e9c1d6fa5aa8fefed8815d07e3992acb9d` |
| Backend parent | `2dc5e56fd25a6bd028700adf92fff9212d06e615` |
| Frontend parent | `bf26df9e431d1364e66098705420aee984073f03` |
| OpenAPI SHA-256 | `C58EF1A6271958173AAFA6FC60D9FE555C44C477E91634B8EBD649F8660E6D41` |
| Alembic code head | `20260923_0038` (one head) |
| Data classification | Synthetic only |

## Engineering evidence

- Backend pytest: **262 passed, 1 skipped**, with one existing Starlette deprecation warning.
- Ruff and strict MyPy passed; MyPy checked 149 source files.
- Frontend Vitest: **79 test files, 287 tests passed**; TypeScript typecheck, ESLint, and production
  build passed.
- Backend and Frontend OpenAPI snapshots are byte-identical at the SHA-256 above. A repeated
  frontend generated-client pass was stable; see the Frontend candidate record for the exact
  generated-types digest.
- The production public smoke passed four configured routes. The Chromium public accessibility
  matrix passed 24/24 route/viewport checks with zero axe violations, keyboard failures, or
  unexpected console errors.
- The onboarding API journey saves empty optional experience and projects/skills stages, rejects an
  unconfirmed final review, preserves required privacy acceptance, and completes against the
  current API contract.
- The project schema carries `project_type`, caps descriptions at 300 characters to match the
  student form, and migrates the added project type as `other` for existing records.

The local configured database was not upgraded or modified. Its recorded revision was `20260923_0036`,
while the code migration graph now has the single head `20260923_0038`; a live database migration,
rollback, staging rehearsal, and restore were not performed for this candidate. The test suite uses
isolated test databases and synthetic fixtures.

The local `.env` enables the development-only Gemini interview-practice pilot. For release pytest,
`INTERVIEW_PRACTICE_PILOT=false` was set in the test process; no `.env` file was changed. This keeps
tests independent from a local opt-in experiment and does not authorize provider use with real
student data.

## Signup policy and authority boundary

The public student signup endpoint can create an active student session/membership. Institution
registration has a separate review flow; that review does not currently mean that every student
account is held for institutional approval. The institution must explicitly choose whether student
admission requires a human-review state. Until the policy is approved, the UI and service must not
promise that the current endpoint performs human review, and no real-data activation is permitted.

No student records, production database, deployment, or external reviewer system was changed by this
validation. The candidate evidence does not establish legal/privacy approval, UAT, current
candidate-specific security approval, operational support and alert ownership, capacity/cost,
artifact provenance, or final real-data authorization. Prior scans and staging/recovery evidence
belong to their recorded source versions unless reviewers bind them to this exact pair.

The authorization register is intentionally unchanged. Keep the product synthetic-only until the
authorized decision-maker closes every required gate and records a candidate-specific `GO` with its
institution, user limits, operating conditions, and expiry.
