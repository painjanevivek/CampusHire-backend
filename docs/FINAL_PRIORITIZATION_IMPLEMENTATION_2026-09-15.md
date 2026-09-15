# Final prioritization implementation record — 2026-09-15

Status: **GO for continued synthetic implementation; NO-GO for real student data.**

This record binds the first implementation increment of the final prioritization plan. It does
not replace `CURRENT_RELEASE_STATUS.md`, grant institutional approval, or qualify a deployable
candidate from a dirty working tree.

## Reproducible technical baseline

| Baseline | Recorded value |
| --- | --- |
| Backend contract authority | `Backend/openapi/campushire.openapi.json` |
| Frontend contract copy | Byte-identical to the backend snapshot |
| OpenAPI SHA-256 | `53a6daa0a7308aa0bd4ad65ee2c7ec70b9241fbf31445c58d95b5f9c45dc6441` |
| Alembic head | `20260915_0032` |
| Backend validation | 226 passed, 1 skipped; Ruff clean; strict MyPy clean across 137 files |
| Frontend validation | 214 passed; ESLint clean; TypeScript clean; production build complete |
| Test data boundary | Synthetic data only |

The repositories contained pre-existing uncommitted authentication, account, documentation, and
landing-page work when this increment started. Those changes were preserved. A release candidate
must be frozen from reviewed commits and all evidence rerun against those exact commits.

## Implemented in this increment

- The application wizard is the only submission path exposed by the student opportunity UI.
- Material terms have tenant-scoped, role-scoped versions with draft, publication, approval,
  effective-date, supersession, and deterministic content-digest evidence.
- Structured terms cover compensation, work location/mode, bond, probation, training, deadline,
  required documents, selection stages, placement restrictions, and additional terms.
- Authorized placement staff can save, publish, read, and compare material-term versions through
  CSRF-protected, permission-gated endpoints. Publication supersedes the previous version.
- A draft pins the latest published material terms. If terms change before submission, the stale
  submission fails closed; the student must load and acknowledge the new version.
- Submission records a first-class acknowledgment and snapshots exact terms, acknowledgment,
  profile, resume, role, rule, eligibility, decision, and disclosure metadata into one canonical
  SHA-256 packet digest.
- ORM enforcement and a PostgreSQL trigger prevent replacement of finalized packet evidence.
- Existing rows receive explicit `legacy_import` provenance and a non-canonical migration digest;
  no historical acknowledgment is fabricated. New roles without published terms are labeled
  `legacy_role_terms_missing` until migration is complete.
- The review screen shows the exact material terms, version, evidence digest, and separate terms
  and accuracy confirmations without adding a new dashboard or landing-page section.

## Remaining exit gates

P0 is not complete until an institutional owner approves the policy vocabulary, appeals, outcomes,
retention, reporting, accessibility, and pilot limits and the representative real-data mapping is
performed outside production. P1 is not complete until all in-scope published roles have material
terms and the compatibility-only direct backend submission endpoint is retired after a measured
migration window.

P2 through P8 remain ordered behind those gates. Existing privacy, appeal, audit, eligibility,
reporting, and AI controls are foundations, not evidence that the new phase exits are satisfied.
No real student data may be introduced to close those gaps.
