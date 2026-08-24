# Release Plan Completion Audit — 2026-08-24

Decision: **NO-GO for a real-data pilot**

This audit maps every action and exit criterion in `campushire-release-completion-plan.md` to executable evidence. “Complete” means repository-controlled work is implemented and locally verified. It does not substitute local evidence for managed-provider proof, representative-user experience, legal approval, or release authority.

## Candidate and phase evidence

| Phase | Repository evidence | Commit evidence | Current outcome |
| --- | --- | --- | --- |
| 7A parser isolation | `docs/PARSER_SANDBOX.md`, `docs/PARSER_ISOLATION_EVIDENCE_2026-08-24.md`, parser protocol/runner/container tests | Backend `3a8d09d` | Local boundary complete; managed launcher proof pending (`KL-001`) |
| 7B security closure | `docs/SECURITY_REVIEW.md`, `docs/THREAT_MODEL.md`, `docs/KNOWN_LIMITATIONS.md` | Deferred by user | Paused; neither Deep Scan is represented as passed |
| 7C staging topology | `docs/ENVIRONMENT_MANIFEST.md`, `docs/STAGING_DEPLOYMENT.md`, `deploy/`, topology rehearsal evidence | Backend `90629dc` | Reproducible local topology complete; managed deployment pending |
| 7D recovery | recovery/dependency scripts and dated rehearsal reports | Backend `fe5932f` | Local rehearsals complete; selected-provider repetition pending |
| 7E capacity | performance script, baseline, and capacity proposal | Backend `50bf17e` | Reproducible local baseline complete; approved pilot envelope pending |
| 7F accessibility/UAT | browser runner, UAT pack/templates, issue template, browser support matrix | Frontend `46b3fa8` | 126 automated checks complete; representative UAT pending |
| 7G governance | privacy, retention, appeals, incident, permission, ownership, cross-check, sign-off drafts | Backend `ae93421`, `da1672f` | Draft/control pack complete; authorized ownership and approvals pending |
| 7H candidate decision | strict manifest generator, release gates, dossier, launch record | Backend `fc03b58` | Strict no-go is enforced; immutable freeze/deployment pending |

## Action-by-action audit

### Phase 7A

| Action | Status | Evidence / remaining condition |
| --- | --- | --- |
| Reconcile upload, scan, parse, job, storage, and deletion paths | Complete | Resume pipeline, architecture, threat model, and integration tests agree. |
| Define a narrow parser protocol | Complete | Bounded input/output protocol and structured error schema are tested. |
| Remove privileged dependencies from native parsing | Complete | Dedicated runner/container receives no application or provider credentials. |
| Enforce sandbox policy and resource limits | Complete locally | Container policy inspection passes; reproduce the exact controls on the managed launcher. |
| Validate strict bounded output | Complete | Schema, size, type, page, and malformed-output tests fail closed. |
| Make crash/timeout cleanup idempotent | Complete | Timeout, crash, retry, cleanup, and duplicate-version tests pass. |
| Add hostile synthetic fixtures | Complete | Safe, malformed, oversized, page-heavy, encrypted, crash, and resource cases are generated without sensitive data. |
| Update operational/security documents | Complete | Parser, resume, threat, deployment, runbook, and limitation records are linked above. |

Exit criterion: **locally proven; not closed for pilot** until managed policy and abuse evidence close `KL-001`.

### Phase 7B

All six scan, triage, remediation, rescan, and report-update actions are **paused by explicit user deferral**. Standard tests and reviews remain controls, not substitutes. Exit criterion: **not met**.

### Phase 7C

| Action | Status | Evidence / remaining condition |
| --- | --- | --- |
| Version the complete environment topology | Complete | Environment manifest and pinned local topology cover frontend, API, worker, parser, PostgreSQL, Redis, storage, ClamAV, Gemini boundary, and optional vector service. |
| Define service identities and secret inventory | Complete as configuration | Names, ownership placeholders, and least-privilege boundaries exist without secret values. |
| Configure transport/session/security/backup/probe controls | Complete as configuration/local rehearsal | Managed HTTPS, provider IAM, schedules, and immutable digests require target access. |
| Deploy ordered roles and migrations | Prepared, external | Deployment order and commands exist; no managed target or credentials were supplied. |
| Seed synthetic data and run smoke journeys | Complete locally | Production-like local topology rehearsal uses synthetic tenant data only. |
| Prove dependency authority boundaries | Complete locally | Tests and evidence preserve PostgreSQL authority and AI/vector non-authority. |

Exit criterion: **not met** until the exact candidate operates on managed HTTPS and is recreated from approved configuration.

### Phase 7D

Migration rollback/roll-forward, backup/restore, record and reference verification, Redis/worker/parser/scanner/storage/AI/vector failure cases, AI-independent core operation, recovery measurements, duplicate-effect checks, and sanitized runbook evidence are **complete locally**. Exit criterion: **not met** until the timed matrix is repeated on selected managed services by the documented operator.

### Phase 7E

Pilot load inputs have conservative **proposed** defaults; reproducible read/write/idempotency/resume/admin/degraded-provider scenarios, repeated local measurements, bottleneck review, and provisional capacity/alert/cost recommendations are complete. No local result is labelled production capacity. Exit criterion: **not met** until product/platform owners approve pilot volume, SLOs, pricing, cost ceiling, and managed HTTPS repetition.

### Phase 7F

| Action | Status | Evidence / remaining condition |
| --- | --- | --- |
| Automate browser, viewport, axe, keyboard, focus, motion, reflow, and errors | Complete | Chromium, Firefox, and WebKit pass 126 route/viewport/engine checks. |
| Prepare synthetic student/admin scripts | Complete | Deterministic UAT session pack and fictional-data boundary exist. |
| Create structured issue intake | Complete | Accessibility UAT issue template captures severity through retest. |
| Facilitate, fix, and rerun | Partially complete | Automated defects were fixed and rerun; representative sessions have not occurred. |
| Produce sanitized acceptance report | Prepared | Template exists and remains explicitly pending rather than fabricated. |

Exit criterion: **not met** until representative student/admin, real Safari keyboard, and qualified screen-reader sessions close blockers and authorized reviewers decide.

### Phase 7G

All five repository actions are complete as drafts/control artifacts: institutional privacy/consent, rights and retention, appeal/manual review, incident and breach communications, permission/approval matrix, audit/support/security/privacy ownership, implementation cross-check, and versioned sign-off register. Exit criterion: **not met** because accountable contacts, institution-specific values, and authorized decisions remain pending.

### Phase 7H

| Action | Status | Evidence / remaining condition |
| --- | --- | --- |
| Freeze SHAs, contract, images, migrations, config, rollback pair | Partial | SHA/OpenAPI capture is executable; image/config/migration/rollback values are not approved or immutable. |
| Run all candidate gates | Complete where authorized | Local engineering gates pass; deferred scans and managed/human gates remain open. |
| Prove prohibited-file exclusion and remote parity | Partial | Frontend is clean and at remote SHA `46b3fa8`; backend has preserved user-owned tracked changes and cannot freeze. No prohibited file is tracked. |
| Generate go/no-go dossier | Complete | Dossier and strict manifest return no-go with explicit blockers. |
| Deploy gradually, observe, stop/rollback on thresholds | Prepared, external | Launch record/runbooks exist; deployment is unauthorized and was not attempted. |
| Record pilot outcome and follow-up | Prepared, external | Sanitized launch record exists; no outcome is invented before a launch. |

Exit criterion: **not met**.

## Final definition of done

| Requirement | Status |
| --- | --- |
| Parser isolation implemented and abuse-tested | Complete locally; managed reproduction pending |
| Separate Deep Scans completed and validated | Deferred / open |
| Production-like managed staging and tenant/security proof | Open |
| Managed recovery and provider-failure rehearsals | Open |
| Approved performance and cost budgets | Open |
| Automated accessibility | Complete |
| Representative student/admin/screen-reader UAT | Open |
| Institutional governance approvals | Open |
| Critical/high security and blocking defect closure | Cannot close before deferred scans/UAT |
| Immutable candidate and rollback pair | Open |
| Authorized controlled pilot and post-release checks | Open |

Repository-controlled preparation is exhausted for the supplied access and authority. The next executable sequence is: close the backend working tree intentionally, authorize separate Deep Scans, supply managed staging access and approved pilot budgets, run managed rehearsals, complete representative UAT and governance sign-off, then generate a strict immutable manifest for the named go/no-go decision.
