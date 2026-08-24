# CampusHire Release Candidate Dossier — 2026-08-24

Decision: **NO-GO for real-data pilot deployment**

This is an evidence-backed status, not a failure of the completed engineering phases. The repository is prepared for the next authorized steps, but release authority and several production-environment proofs are absent.

## Candidate snapshot

| Artifact | Observed value | Freeze status |
| --- | --- | --- |
| Frontend commit | `46b3fa8f3b19df437498787952fabdbbf5237b77` | Remote parity confirmed; tracked worktree clean |
| Backend commit | Captured by `scripts/build_release_candidate_manifest.py` | Draft run: remote parity confirmed; worktree contains pre-existing user changes, so not immutable |
| OpenAPI hash | `cdd29daf9ca99f96dc31e69e28afc2dd58aa4bb99a27f579457eb5e10f8f2ab4` in the draft run | Recompute and freeze after a clean candidate |
| Frontend/backend images | Local OCI digests and archive hash in `docs/IMMUTABLE_CANDIDATE_EVIDENCE_2026-08-24.md` | Locally frozen; private-registry promotion/signing pending |
| Migration head/config manifest | `20260824_0010`; deterministic bundle hash recorded with the images | Locally frozen; managed values/approval pending |
| Rollback pair | Explicit source/image/archive identifiers and smoke evidence recorded | Locally verified; registry promotion and managed rehearsal pending |

## Verified engineering evidence

- Backend Ruff, strict MyPy, dependency consistency, `81 passed / 1 skipped`, parser isolation, tenant topology, recovery/dependency rehearsals, and local capacity evidence pass.
- Frontend OpenAPI drift, ESLint, TypeScript, `70 passed`, production build, zero dependency vulnerabilities, release smoke, and 126-check Chromium/Firefox/WebKit rendered accessibility matrix pass.
- Credential-free parser boundaries, deterministic eligibility, durable jobs/deletion, audit evidence, and degraded AI/provider operation are documented and tested locally.
- Prohibited contributor guidance, design references, local skills, and generated evidence are excluded from release tracking.

## Blocking gates

1. Frontend and backend exhaustive Deep Security Scans remain explicitly deferred.
2. Managed staging, managed backup/restore, selected-provider failure drills, and managed HTTPS capacity repetition are incomplete.
3. Provider pricing, pilot size, cost ceiling, and production SLO/alert approval are pending.
4. Representative student, administrator, keyboard, and screen-reader UAT plus independent retest/acceptance are pending.
5. Privacy/legal, T&P, accessibility, product, security/platform, audit-access, ownership, and after-hours approvals are pending.
6. Backend tracked user changes must be intentionally committed or reverted by their owner before candidate freeze.
7. No target deployment access, approved private-registry promotion/signing evidence, or authorized go/no-go decision is available. Local immutable image/configuration/rollback evidence is complete but is not a managed deployment.

## Launch/rollback decision

No deployment was attempted because doing so would bypass explicit plan authority and release gates. After blockers close, generate a strict manifest, attach controlled evidence, obtain the named go/no-go decisions, follow `docs/DEPLOYMENT_RECOVERY.md`, and use `docs/PILOT_LAUNCH_RECORD.md` for monitored rollout. Any critical/high security or accessibility finding, tenant leakage, data loss, dishonest decision authority, failed restore, or threshold breach requires stop/rollback.
