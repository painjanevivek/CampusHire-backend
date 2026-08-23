# Backend Implementation Inventory

This inventory maps backend capability through Phase 2 without treating domain-only code as an integrated API.

| Domain | Current disposition | Owner phase |
| --- | --- | --- |
| Health, request correlation, security headers and structured errors | Implemented and tested | 1 and 6 |
| Authentication, sessions, CSRF, rate limiting and revocation | Implemented; Phase 1 adds session-bound CSRF rotation and active institution membership | 1 |
| Institutions and memberships | Institution model existed; verified membership lifecycle, active session context and negative authorization tests added in Phase 1 | 1 |
| Audit | Durable event model existed; Phase 1 centralizes event creation and adds resource/outcome/correlation context | 1 through 6 |
| Student profile | Institution-scoped aggregate and subresource APIs use optimistic revisions and reject stale writes | Complete in 2 |
| Resume | Private quarantine, mandatory scanning, PostgreSQL-authoritative jobs, reviewed extraction/suggestions, immutable versions and owner-only downloads | Complete in 2 |
| Recruitment and eligibility | Deterministic domain primitives and tests exist; persistent companies, drives, roles, applications and APIs remain | 3 |
| Matching and policy | Bounded scoring, institution metadata and grounded workflow primitives exist; provider adapters, persistence and reviewed APIs remain | 4 |
| Roadmaps and notifications | Domain validation and safety rules exist; persistence and user/admin APIs remain | 5 |

The backend OpenAPI document is authoritative. Run `.venv/Scripts/python.exe scripts/export_openapi.py` on Windows or `python scripts/export_openapi.py` in CI, then review `openapi/campushire.openapi.json`.

## Phase 2 operational boundary

`python -m app.worker` runs the supervised resume worker separately from the API. Development may use the deterministic marker scanner; staging and production require ClamAV. Redis is an optional wake-up signal only: durable job state, retry scheduling, heartbeats and recovery remain authoritative in PostgreSQL. See `docs/RESUME_PIPELINE.md` for the failure model.
