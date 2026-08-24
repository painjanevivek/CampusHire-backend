# Production-like staging deployment

The versioned stack in `deploy/staging/compose.yaml` is the provider-neutral release topology. It exposes only the HTTPS gateway; PostgreSQL, Redis, Qdrant, ClamAV, the API, and private resume storage remain on internal networks. API, worker, frontend, and parser references must be immutable registry digests.

## Required protected inputs

Create an ignored deployment environment file from `deploy/staging/.env.template`. Generate independent PostgreSQL and Redis passwords in a directory outside the repository as `postgres_password` and `redis_password`. Supply `DATABASE_URL`, `REDIS_URL`, and `GEMINI_API_KEY` through the selected secret manager. Never place populated values in Git, CI logs, tickets, or release evidence.

The worker requires `PARSER_DOCKER_HOST` to point to an approved isolated, authenticated rootless launcher and `PARSER_CLIENT_CERT_DIR` to contain its narrow mutual-TLS client identity. Do not mount a host Docker socket into the worker. Load the exact `RESUME_PARSER_IMAGE` digest into that launcher and reproduce `docs/PARSER_SANDBOX.md` policy checks there.

## Deployment order

1. Build and publish the backend `api` and `worker` targets, the parser and ClamAV images, and the frontend image.
2. Record commit SHAs, image digests, OpenAPI hash, and configuration version.
3. Run `docker compose --env-file <protected-file> -f deploy/staging/compose.yaml config` and review the resolved topology without printing secrets into evidence.
4. Start dependencies and the one-shot `migrate` service. The API and worker start only after migration succeeds.
5. Start the frontend and gateway, then verify HTTPS, health probes, secure cookies, CSP/HSTS, tenant-negative tests, synthetic student/admin journeys, parser policy, and degraded Gemini behavior.

`scripts/seed_staging_synthetic.py` creates only standards-reserved `example.com` test identities in two synthetic institutions. It requires three passwords through the process environment and prints no password. Export its second institution identifier as `STAGING_SECOND_INSTITUTION_ID`, then run `scripts/smoke_staging.py --base-url https://<host> --environment-label <label>`. The `--insecure-local-tls` option is restricted to labels beginning with `local-`; never use it for managed staging.

## Secret ownership inventory

| Name | Consumer | Proposed owner | Rotation trigger |
| --- | --- | --- | --- |
| `DATABASE_URL` / `postgres_password` | API, worker, migration | Platform database owner | exposure, personnel change, scheduled rotation |
| `REDIS_URL` / `redis_password` | API, worker | Platform cache owner | exposure or scheduled rotation |
| `GEMINI_API_KEY` | bounded AI adapter only | Product AI owner | exposure, quota incident, provider rotation |
| Gateway private key / local CA | gateway | Platform TLS owner | certificate lifecycle or key exposure |
| Parser launcher client identity | worker only | Platform security owner | worker/launcher compromise or scheduled rotation |

Managed-provider access, DNS, public certificates, backup policy, and provider-specific identities are external Phase 7C gates. Local TLS or Docker evidence must be labelled local and cannot authorize real student data.

## OCI Always Free target

`deploy/oci/` supplies the public Caddy policy, an ARM64 single-VM resource envelope, protected-environment validation, and the operator contract for an OCI Ampere A1 staging host. The GitHub publication workflows produce AMD64/ARM64 images with immutable digests, SBOMs, and provenance; `Deploy OCI staging` transfers only the committed deployment bundle and protected runtime configuration. Follow `deploy/oci/README.md`. This is a cost-constrained staging target, not evidence of high availability or production capacity.
