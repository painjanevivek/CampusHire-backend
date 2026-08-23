# Environment Manifest

## Deployable artifacts

- **Frontend:** immutable Next.js 16 image/artifact, configured with the public HTTPS API origin. It does not contain database, provider, or storage credentials.
- **Backend API:** immutable FastAPI image exposing `/api/v1`, with PostgreSQL, Redis, Qdrant, object storage, scanner, and Gemini configuration supplied by the deployment secret manager.
- **Worker:** the same reviewed backend release or a separately pinned worker artifact. It consumes durable PostgreSQL jobs and uses bounded leases; parsing must run in a credential-free isolated process before pilot uploads.

## Required services

| Service | Authority | Persistence | Pilot requirement |
| --- | --- | --- | --- |
| PostgreSQL | Authoritative records, decisions, versions, audit metadata | Durable, backed up | TLS, PITR/logical backup, restore rehearsal |
| Redis | Sessions, rate limits, cache, locks | Ephemeral/reconstructable | authentication fail-closed in production |
| Qdrant | Versioned semantic vectors | Derived/rebuildable | institution filter and reviewed-fact rebuild |
| Object storage | Quarantined, original, generated private files | Durable/versioned | private buckets, lifecycle, malware state |
| Gemini | Bounded extraction/matching assistance | No authority | minimized inputs, timeouts, budgets, disable switch |
| Scanner/parser runtime | File validation and extraction | No durable authority | patched, resource-capped, network/credential isolation |

## Environment classes

- **Development:** synthetic data; SQLite and controlled adapters are allowed; results must be labelled non-production.
- **CI:** PostgreSQL 16 migration upgrade/downgrade/upgrade, unit/integration/contract/security tests, frontend lint/type/test/build.
- **Staging:** production-shaped topology and representative minimized fixtures; required for provider, performance, recovery, accessibility, and release rehearsal.
- **Production pilot:** institution-approved configuration, contacts, retention, SLO/RTO/RPO, secrets, monitoring, backups, and signed release decision.

Use `.env.example` only as a variable inventory. Never commit populated `.env` files, credentials, provider payloads, or recovery exports. Record immutable commit/image identifiers and configuration version—not secret values—in the release evidence pack.
