# CampusHire release evidence matrix

This matrix names executable evidence, not production approval. Human and hosting-provider gates remain in `docs/RELEASE_GATES.md`.

| Requirement group | Backend evidence | Frontend / cross-repo evidence | Remaining external gate |
| --- | --- | --- | --- |
| FR-001–003 identity and profile | `tests/test_auth.py`, `tests/test_profile_resume_pipeline.py` | generated OpenAPI check; onboarding component tests | institution roster and support-owner approval |
| FR-004–007 resume and opportunities | resume pipeline, credential-free parser/container policy, shared-VM worker/ClamAV/private-storage/parser completion, eligibility, matching, and policy tests | resume/opportunity tests; loading, empty, unavailable, and failed states | representative student review and real-data authorization |
| FR-008–012 applications and administration | recruitment, authorization, audit, operation, and override tests | admin workspace and operations tests | administrator UAT and policy sign-off |
| FR-013–016 roadmap and notifications | roadmap/notification tests and phase smoke runner | dashboard, roadmap, notification, and safe-link tests | student UAT and accessibility review |
| NFR security and privacy | auth/CSRF/CORS/upload/tenant tests, dependency checks, deletion tests, threat model, parser isolation plus shared-VM rootless-launcher evidence | CSP/API-destination tests, dependency audit | Deep Scans explicitly deferred and the active Frontend run canceled (not passed); governance/UAT conditions remain |
| NFR accessibility and responsive UX | semantic OpenAPI errors | Testing Library + axe shell checks, production build, 126-check Chromium/Firefox/WebKit matrix, complete keyboard traversal, motion/forced-colors/200% reflow checks | real Safari/macOS keyboard and screen-reader review with pilot users |
| NFR reliability and recovery | local full fault matrix plus `scripts/rehearse_shared_vm_recovery.sh`, `scripts/rehearse_shared_vm_dependencies.sh`, timed isolated restore/rollback/forward evidence, authoritative-count checks, fail-closed Redis/PostgreSQL behavior, dependency recovery, idempotency, and parser cleanup | contract check, standalone image, release smoke, rollback guide, and failure-state tests | provider-specific repetition if the deployment moves away from the selected self-managed topology |
| NFR performance | shared-VM HTTPS concurrency-10 HTTP/idempotency/degraded-provider evidence, three real scanner/parser jobs, post-run resource snapshot, parameterized cost model, and deterministic evaluation metadata | production build and public-route release smoke | approved pilot volume, provider pricing, SLO, alert, and cost envelope |
| Pilot acceptance | backend scenario pack and known-limitations register | student/admin UAT, keyboard/mobile/reduced-motion browser matrix | named stakeholder, accessibility, privacy, and security approvals |
| Governance closure | privacy, rights/retention, appeal, incident, permission, ownership, cross-check, and sign-off drafts | sanitized UAT acceptance record | institution-specific contacts, periods, legal basis, owner assignment, and authorized approvals |
| Candidate freeze and launch | release-manifest generator, immutable GHCR deployment digests, protected shared-VM deployment, recovery runbook, post-deploy smoke evidence, and controlled launch record | frontend deployed digest, candidate SHA, and browser/accessibility evidence | signing policy, representative UAT, deferred scans, governance conditions, and real-data go/no-go activation |

No flaky test is quarantined. A future quarantine must identify an owner, reason, issue, and expiry date in the same change.
