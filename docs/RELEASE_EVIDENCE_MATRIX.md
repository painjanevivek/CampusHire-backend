# CampusHire release evidence matrix

This matrix names executable evidence, not production approval. Human and hosting-provider gates remain in `docs/RELEASE_GATES.md`.

| Requirement group | Backend evidence | Frontend / cross-repo evidence | Remaining external gate |
| --- | --- | --- | --- |
| FR-001–003 identity and profile | `tests/test_auth.py`, `tests/test_profile_resume_pipeline.py` | generated OpenAPI check; onboarding component tests | institution roster and support-owner approval |
| FR-004–007 resume and opportunities | resume pipeline, credential-free parser/container policy, worker recovery, eligibility, matching, and policy tests | resume/opportunity tests; loading, empty, unavailable, and failed states | managed ClamAV, object-store, and parser-launcher staging validation |
| FR-008–012 applications and administration | recruitment, authorization, audit, operation, and override tests | admin workspace and operations tests | administrator UAT and policy sign-off |
| FR-013–016 roadmap and notifications | roadmap/notification tests and phase smoke runner | dashboard, roadmap, notification, and safe-link tests | student UAT and accessibility review |
| NFR security and privacy | auth/CSRF/CORS/upload/tenant tests, dependency checks, deletion tests, threat model, parser isolation evidence | CSP/API-destination tests, dependency audit | Deep Scans explicitly deferred (not passed); managed parser policy and cross-boundary staging review remain |
| NFR accessibility and responsive UX | semantic OpenAPI errors | Testing Library + axe shell checks, production build, manual browser matrix | screen-reader review with pilot users |
| NFR reliability and recovery | `scripts/rehearse_postgres_recovery.ps1`, `scripts/rehearse_dependency_failures.py`, timed PostgreSQL 17 rollback/restore report, preserved application/audit/object/queue evidence, duplicate-effect checks, parser policy evidence, and the Phase 7C topology rehearsal | contract check, standalone image, release smoke, rollback guide, and failure-state tests | managed staging restore and selected-vendor repetition of the dependency matrix |
| NFR performance | `scripts/measure_pilot_http.py`, measured local HTTP baseline, deterministic evaluation metadata, request duration logs | production build and public-route release smoke | representative staging load, approved SLOs/cost ceilings, and worker throughput |
| Pilot acceptance | backend scenario pack and known-limitations register | student/admin UAT, keyboard/mobile/reduced-motion browser matrix | named stakeholder, accessibility, privacy, and security approvals |

No flaky test is quarantined. A future quarantine must identify an owner, reason, issue, and expiry date in the same change.
