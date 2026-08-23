# Backend Implementation Inventory

This Phase 1 baseline maps current backend capability to the MVP requirements without treating domain-only code as an integrated API.

| Domain | Current disposition | Owner phase |
| --- | --- | --- |
| Health, request correlation, security headers and structured errors | Implemented and tested | 1 and 6 |
| Authentication, sessions, CSRF, rate limiting and revocation | Implemented; Phase 1 adds session-bound CSRF rotation and active institution membership | 1 |
| Institutions and memberships | Institution model existed; verified membership lifecycle, active session context and negative authorization tests added in Phase 1 | 1 |
| Audit | Durable event model existed; Phase 1 centralizes event creation and adds resource/outcome/correlation context | 1 through 6 |
| Student profile | Base persistence and readiness helpers exist; progressive subresources and conflict handling remain | 2 |
| Resume | PDF validation, extraction/generation and versions exist; object storage, scanning, durable jobs and review decisions remain | 2 |
| Recruitment and eligibility | Deterministic domain primitives and tests exist; persistent companies, drives, roles, applications and APIs remain | 3 |
| Matching and policy | Bounded scoring, institution metadata and grounded workflow primitives exist; provider adapters, persistence and reviewed APIs remain | 4 |
| Roadmaps and notifications | Domain validation and safety rules exist; persistence and user/admin APIs remain | 5 |

The backend OpenAPI document is authoritative. Run `.venv/Scripts/python.exe scripts/export_openapi.py` on Windows or `python scripts/export_openapi.py` in CI, then review `openapi/campushire.openapi.json`.
