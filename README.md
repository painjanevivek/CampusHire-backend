# CampusHire AI Backend

The backend is the secure source of business rules, persistence, document processing, AI orchestration, and the versioned `/api/v1` contract for CampusHire AI.

## Local development

1. Copy `.env.example` to `.env`.
2. Start PostgreSQL with `docker compose up -d postgres`.
3. Create and activate a Python virtual environment.
4. Install dependencies with `python -m pip install -e ".[dev]"`.
5. Run migrations with `alembic upgrade head`.
6. Start the API with `uvicorn app.main:app --reload`.
7. Build the local parser sandbox with `docker build -f Dockerfile.parser -t campushire-pdf-parser:local .`.
8. In a second terminal, start durable document jobs with `python -m app.worker`.

The API is available at `http://localhost:8000`, with versioned routes under `/api/v1`.

When port 8000 is occupied, set `APP_PORT=8001` and include the exact frontend origin, for example `FRONTEND_ORIGINS='["http://127.0.0.1:3002"]'`, before running `uvicorn app.main:app --reload --port 8001`. Keep origin and cookie configuration environment-specific.

### Synthetic demo sign-in

For local development or automated test environments only, set `DEMO_LOGIN_ENABLED=true`, provide the four `DEMO_STUDENT_*` and `DEMO_ADMIN_*` values shown in `.env.example`, then run `python scripts/seed_demo_accounts.py`. The `/api/v1/auth/demo-sign-in` endpoint chooses those credentials on the server; passwords are never sent to the browser. Student demo sign-in creates a normal session. Set `DEMO_ADMIN_MFA_BYPASS=true` only when the synthetic T&P demo must skip MFA during local testing; the bypass is recorded in the audit log and is rejected outside development/test. Normal administrator sign-in still requires MFA. Configuration validation prevents demo sign-in from being enabled in staging or production.

## Checks

```text
ruff check .
mypy app
pytest
python scripts/export_openapi.py
python scripts/evaluate_matching.py
```

## Boundaries

- PostgreSQL is the durable source of truth.
- Redis is temporary operational infrastructure, not the business database.
- Qdrant stores versioned embeddings, not authoritative profile or decision records.
- Deterministic services decide eligibility.
- LangGraph is limited to bounded multi-step AI workflows.
- Core recruitment operations remain available during AI-provider outages.

Project-level scope and architecture decisions are maintained in the [frontend repository](https://github.com/painjanevivek/CampusHire/tree/main/docs). Backend-specific implementation documentation will live in this repository as modules are introduced.

Resume uploads are quarantined before parsing. The default `marker` scanner and subprocess parser are only for deterministic local development and tests. Staging and production must set `MALWARE_SCANNER=clamav`, use the container parser, and provide an approved rootless launcher; see `docs/RESUME_PIPELINE.md` and `docs/PARSER_SANDBOX.md`.
