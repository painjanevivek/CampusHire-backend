# API Contract Governance

`openapi/campushire.openapi.json` is the authoritative reviewed snapshot for `/api/v1`.

1. Change schemas and routes with focused backend tests.
2. Run `python scripts/export_openapi.py`.
3. Review the OpenAPI diff for removals, renamed fields, status changes, and new authorization requirements.
4. Copy the approved snapshot to the frontend `openapi/` directory and run `npm run api:generate`.
5. Commit backend and frontend compatibility changes in their independent repositories.

Backend CI re-exports the schema and fails on an uncommitted contract diff. Frontend CI regenerates TypeScript declarations and fails on drift. Breaking changes require an explicit versioned endpoint or a coordinated compatibility window; hand-written duplicate transport types are not authoritative.
