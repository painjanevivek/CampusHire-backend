# CampusHire AI Backend

The backend is the secure source of business rules, persistence, document processing, AI orchestration, and the versioned `/api/v1` contract for CampusHire AI.

## Current status

Phase 0 establishes product and engineering governance. FastAPI, PostgreSQL, development services, tests, and CI are introduced in Phase 1.

## Boundaries

- PostgreSQL is the durable source of truth.
- Redis is temporary operational infrastructure, not the business database.
- Qdrant stores versioned embeddings, not authoritative profile or decision records.
- Deterministic services decide eligibility.
- LangGraph is limited to bounded multi-step AI workflows.
- Core recruitment operations remain available during AI-provider outages.

Project-level scope and architecture decisions are maintained in the [frontend repository](https://github.com/painjanevivek/CampusHire/tree/main/docs). Backend-specific implementation documentation will live in this repository as modules are introduced.
