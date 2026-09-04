# Vercel API deployment

This runbook deploys the CampusHire FastAPI request application to Vercel. It
does not move the durable worker, ClamAV daemon, or Docker PDF parser into a
Vercel Function. Those components must continue running on an always-on host
against the same PostgreSQL, Redis, Qdrant, and OCI Object Storage services.

## Architecture boundary

- Vercel runs `app.main:app` with `PROCESS_ROLE=api`.
- The API validates requests, persists jobs, and uploads quarantined PDFs to OCI.
- The external process runs `python -m app.worker` with `PROCESS_ROLE=worker`.
- The worker alone requires `MALWARE_SCANNER=clamav` and
  `RESUME_PARSER_BACKEND=docker` in staging and production.
- Database migrations run before promotion, never during application startup.

## Vercel project

Import the backend Git repository as its own Vercel project. Use the repository
root as the Root Directory and let Vercel detect the Python/FastAPI application.
The entrypoint is declared in `pyproject.toml`; do not add a custom build command
or output directory.

Connect a stable HTTPS domain such as `api.campushire.example`. The frontend and
API should use sibling domains under the same registrable domain so the existing
`SameSite=Strict` authentication cookies remain same-site.

## Production environment

Set these values in the Vercel Production environment. Replace every placeholder
and copy any additional enabled-service values from `.env.example`.

```dotenv
APP_ENV=production
PROCESS_ROLE=api
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@MANAGED-POOLER/DATABASE
REDIS_URL=rediss://MANAGED-REDIS
QDRANT_URL=https://MANAGED-QDRANT
FRONTEND_ORIGINS=["https://app.campushire.example"]
TRUSTED_HOSTS=["api.campushire.example","BACKEND-PROJECT.vercel.app"]
DEMO_LOGIN_ENABLED=false
DEMO_ADMIN_MFA_BYPASS=false
OPERATOR_BOOTSTRAP_KEY=GENERATE_AT_LEAST_24_RANDOM_CHARACTERS
MFA_ENCRYPTION_KEY=GENERATE_A_DEDICATED_SECRET
RESUME_STORAGE_BACKEND=oci
OCI_AUTH_MODE=api_key
OCI_OBJECT_NAMESPACE=OCI_NAMESPACE
OCI_OBJECT_BUCKET=PRIVATE_BUCKET
OCI_OBJECT_UPLOADS_ENABLED=true
OCI_TENANCY_OCID=ocid1.tenancy.oc1..REPLACE
OCI_USER_OCID=ocid1.user.oc1..REPLACE
OCI_KEY_FINGERPRINT=REPLACE
OCI_REGION=ap-mumbai-1
OCI_PRIVATE_KEY=PASTE_THE_COMPLETE_PEM_AS_A_SECRET
OCI_PRIVATE_KEY_PASSPHRASE=
GEMINI_API_KEY=
EMAIL_SMTP_HOST=
EMAIL_SMTP_PORT=587
EMAIL_SMTP_USERNAME=
EMAIL_SMTP_PASSWORD=
EMAIL_FROM_ADDRESS=no-reply@campushire.example
EMAIL_DELIVERY_WEBHOOK_KEY=
```

Use the database provider's transaction-pooler URL when it offers one. The API
role disables SQLAlchemy's process-local connection pool so the external pooler
owns connection reuse across short-lived Vercel instances.

Store the OCI private key and every other credential only as encrypted Vercel
environment variables. Do not add PEM files or populated `.env` files to Git.
Grant the OCI user access only to the private CampusHire bucket and rotate the
key under the normal credential runbook.

## External worker environment

The external worker uses the same durable service URLs and bucket:

```dotenv
APP_ENV=production
PROCESS_ROLE=worker
MALWARE_SCANNER=clamav
RESUME_PARSER_BACKEND=docker
RESUME_STORAGE_BACKEND=oci
OCI_AUTH_MODE=instance_principal
```

If the worker does not run on OCI Compute, use `OCI_AUTH_MODE=api_key` and provide
the five API-key identity values instead. Keep the ClamAV and parser networking
private and follow `RESUME_PIPELINE.md` and `PARSER_SANDBOX.md`.

## Release sequence

1. Provision the managed database, Redis, Qdrant, and private OCI bucket.
2. Apply migrations from a trusted runner with `alembic upgrade head`.
3. Start or update the external worker and verify it can claim a test job.
4. Deploy the backend to a Vercel Preview environment.
5. Check `/api/v1/health/live` and `/api/v1/health/ready`.
6. Upload a harmless PDF and verify the external worker scans and parses it.
7. Verify login, CSRF-protected mutation, logout, and administrator MFA flows.
8. Promote the already-verified deployment to Production.

Do not allow authenticated browser previews from arbitrary `*.vercel.app`
origins. Credentialed CORS requires explicit origins. Use a stable preview alias
with isolated preview data, or keep authenticated previews disabled.
