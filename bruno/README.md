# CampusHire API checks with Bruno

This collection covers the local FastAPI HTTP boundary. It has a fast health/authentication smoke layer and a sequential synthetic-student journey. Request paths and response contracts follow `openapi/campushire.openapi.json`.

## Start the local backend

From `Backend/`, start the documented local dependencies and API:

```powershell
docker compose up -d postgres redis
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The `local` collection environment targets `http://127.0.0.1:8000/api/v1`. The readiness check expects PostgreSQL to be available. The student journey also requires the local development configuration to enable the synthetic demo student login and its matching seeded account. Keep those credentials in the ignored backend `.env`; never add them to this collection or commit them.

## Run the collection

From `Backend/` in a second terminal:

```powershell
Set-Location bruno/campushire-api
bru run --env local
```

The collection currently runs eighteen requests: four health/authentication smoke requests, seven existing student journey requests, and seven requests in `Phase 08 release smoke`. Run the collection from its root so the phase 08 requests reuse the signed-in session from the existing student journey. That flow signs in as the local synthetic demo student **Aarav Sharma**, reads and updates the same profile values with the current revision, finds an eligible unsubmitted opportunity, starts or resumes its application draft, then checks onboarding. The phase 08 requests verify that empty experience and projects/skills steps can be skipped, `project_type` survives a subsequent onboarding read, and review confirmation rejects `false` before accepting `true`. The flow signs out at the end.

The city and name in the student assertions describe the current local demo fixture. Update those assertions alongside any intentional changes to that fixture.

## Scope and safety

Bruno checks route availability, response contracts, authentication/CSRF behavior, and journeys crossing the HTTP boundary. Keep domain/service tests in pytest. CampusHire is a modular API with a separately supervised worker, rather than independently deployed microservices. Worker processing is not covered yet; add it only when a local synthetic document-processing stack is available.

The collection does not create accounts or send email. It updates the local synthetic profile and onboarding state, creates or resumes one local application draft, and completes onboarding review. Do not run this mutating journey against production or a shared environment. Keep CI on isolated services and synthetic fixtures, and redact cookies, authorization headers, and request bodies from saved reports.
