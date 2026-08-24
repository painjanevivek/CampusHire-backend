# Shared VM staging

This target deploys CampusHire beside an existing Docker-based HTTPS gateway. It supports
AMD64 and ARM64 Linux hosts and preserves the credential-free rootless parser boundary. It is
for synthetic staging and controlled pilot rehearsal, not high-availability production.

## Host contract

- Docker Engine and Compose are installed.
- A non-root deployment user owns `/opt/campushire` and may access the main Docker daemon.
- A separate OS user runs rootless Docker with mutual TLS on private host port `2376`.
- The firewall denies public access to `2376`; only private Docker networks may reach it.
- `ca.pem`, `cert.pem`, and `key.pem` are mode `0600` in
  `/opt/campushire/config/parser-client-tls`.
- An existing gateway network is supplied as `SHARED_GATEWAY_NETWORK`.
- The gateway imports `Caddyfile.site`, substitutes `STAGING_HOST`, and can resolve the
  `campushire-api` and `campushire-frontend` aliases on the shared network.

The application does not publish host ports and does not replace the existing gateway. Keep
PostgreSQL, Redis, Qdrant, ClamAV, and the parser endpoint private.

## GitHub staging environment

Set `VM_SSH_HOST`, `VM_SSH_USER`, `STAGING_HOST`, and `SHARED_GATEWAY_NETWORK` as environment
variables. Set `VM_SSH_PRIVATE_KEY`, `VM_SSH_HOST_KEY`, `POSTGRES_PASSWORD`, and
`REDIS_PASSWORD` as environment secrets. `GEMINI_API_KEY` remains optional.

Publish the frontend with `https://<staging-host>/api/v1`, then dispatch
`Deploy shared VM staging` with immutable digest-qualified images. Seed synthetic data and run
smoke, parser-isolation, dependency-failure, recovery, and capacity rehearsals before admitting
any real student data.
