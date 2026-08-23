# CampusHire release evidence matrix

This matrix names executable evidence, not production approval. Human and hosting-provider gates remain in `docs/RELEASE_GATES.md`.

| Requirement group | Backend evidence | Frontend / cross-repo evidence | Remaining external gate |
| --- | --- | --- | --- |
| FR-001–003 identity and profile | `tests/test_auth.py`, `tests/test_profile_resume_pipeline.py` | generated OpenAPI check; onboarding component tests | institution roster and support-owner approval |
| FR-004–007 resume and opportunities | resume pipeline, worker recovery, eligibility, matching, and policy tests | resume/opportunity tests; loading, empty, unavailable, and failed states | ClamAV and object-store staging validation |
| FR-008–012 applications and administration | recruitment, authorization, audit, operation, and override tests | admin workspace and operations tests | administrator UAT and policy sign-off |
| FR-013–016 roadmap and notifications | roadmap/notification tests and phase smoke runner | dashboard, roadmap, notification, and safe-link tests | student UAT and accessibility review |
| NFR security and privacy | auth/CSRF/CORS/upload/tenant tests, dependency checks, deletion tests | CSP/API-destination tests, dependency audit | separate Deep Scans and cross-boundary review |
| NFR accessibility and responsive UX | semantic OpenAPI errors | Testing Library + axe shell checks, production build, manual browser matrix | screen-reader review with pilot users |
| NFR reliability and recovery | PostgreSQL migration rehearsal, job lease/retry tests, provider fakes | contract check and failure-state tests | staging backup restore and worker kill drill |
| NFR performance | deterministic evaluation metadata and request duration logs | bundle/build evidence | representative staging load baseline |

No flaky test is quarantined. A future quarantine must identify an owner, reason, issue, and expiry date in the same change.
