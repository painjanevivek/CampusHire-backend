# CampusHire AI Backend

The backend is the secure source of business rules, persistence, document processing, AI orchestration, and the versioned `/api/v1` contract for CampusHire AI.

## Local development

1. Copy `.env.example` to `.env`.
2. Start PostgreSQL with `docker compose up -d postgres`.
3. Create and activate a Python virtual environment.
4. Install dependencies with `python -m pip install -e ".[dev]"`.
5. Run migrations with `alembic upgrade head`.
6. Start the API with `uvicorn app.main:app --reload`.

The API is available at `http://localhost:8000`, with versioned routes under `/api/v1`.

## Checks

```text
ruff check .
mypy app
pytest
```

## Boundaries

- PostgreSQL is the durable source of truth.
- Redis is temporary operational infrastructure, not the business database.
- Qdrant stores versioned embeddings, not authoritative profile or decision records.
- Deterministic services decide eligibility.
- LangGraph is limited to bounded multi-step AI workflows.
- Core recruitment operations remain available during AI-provider outages.

Project-level scope and architecture decisions are maintained in the [frontend repository](https://github.com/painjanevivek/CampusHire/tree/main/docs). Backend-specific implementation documentation will live in this repository as modules are introduced.
