# Architecture and operations baseline

This document is the code-owned portion of Wave 0 from the CampusHire architecture review. It is intentionally factual: business retention periods, legal holds, hosting topology, and incident contacts are product/platform decisions and are not invented here.

## Runtime ownership

| Component | Durable authority | Operational dependency | Owner boundary |
|---|---|---|---|
| FastAPI API | PostgreSQL | Redis for rate limits; private object storage; AI/vector adapters | Backend |
| Worker | PostgreSQL job records | Scanner, object storage, AI adapters | Backend/Platform |
| Next.js | None for business data | Versioned backend OpenAPI | Frontend |
| PostgreSQL | Users, memberships, profiles, resumes, placement records, audit records | Backup/restore managed by platform | Platform |
| Redis | No durable business state | Rate limits, locks, cache/wakeups only | Platform |
| Qdrant | Rebuildable embedding projection only | PostgreSQL source and deletion events | AI/Backend |

## Tenant policy matrix

Tenant-owned operations receive a server-derived `TenantContext`, created from the active session and membership. Browser input must not determine an institution for authorization.

| API area | Required role | Tenant boundary | Test evidence |
|---|---|---|---|
| Profile and resume | Authenticated student | Own `user_id`; active institution when present | `tests/test_profile_resume_pipeline.py` |
| Student opportunities and applications | Student | `TenantContext.institution_id` plus own `user_id` | `tests/test_recruitment_operations.py` |
| Recruitment administration | TNP administrator | Institution-scoped service queries | `tests/test_recruitment_operations.py` |
| Membership administration | TNP administrator | Active institution | `tests/test_auth.py` |

When adding a tenant-owned route, add a foreign-institution integration test in the same change. Return a generic not-found outcome where a resource's existence should not be disclosed.

## Data classification

| Class | Examples | Handling rule |
|---|---|---|
| Restricted personal data | Resume content, phone number, date of birth, education | Never place in logs, public URLs, analytics payloads, or client-side secrets. |
| Sensitive operational data | Sessions, audit history, role/application state | PostgreSQL authority, least-privilege access, protected backups. |
| Rebuildable projection | Embeddings, caches | Include source revision and remove/rebuild when source data is deleted or corrected. |
| Public recruitment data | Published company/drive/role information | Still institution-scoped until an explicit public publication feature exists. |

## Required operational evidence before production

- Platform owner records production/staging topology, secret rotation, backup RPO/RTO, storage IAM, and incident contacts.
- Product owner approves retention periods, deletion/anonymization exceptions, and the student data notice.
- Backend team runs a non-production restore drill and captures the result in the release evidence.
- Every external provider has a documented data-processing purpose and failure mode.

