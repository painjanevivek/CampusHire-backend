# OCI Always Free staging

This target runs the production-shaped CampusHire staging stack on one OCI Ampere A1 VM. It is intended for synthetic-data rehearsal and a controlled pilot, not a high-availability production launch. The base topology remains in `../staging/compose.yaml`; `compose.override.yaml` adds limits sized for 2 OCPUs and 12 GB RAM.

## Provisioning contract

Provision an Ubuntu ARM64 VM with 2 OCPUs, 12 GB RAM, and 100-150 GB of boot volume in the tenancy's home region. Reserve its public IP. Permit inbound TCP 80/443, restrict TCP 22 to the operator's IP, and do not expose PostgreSQL, Redis, Qdrant, ClamAV, Docker, or the parser launcher.

Install a supported Docker Engine with the Compose and rootless extras plugins. Create an unprivileged deployment user that owns `/opt/campushire`; its SSH key is dedicated to GitHub staging deployments. Builds happen in GitHub Actions, not on the constrained VM.

Create a second unprivileged OS identity for the parser launcher. Run its rootless Docker daemon with mutual TLS on TCP 2376, issue a client certificate only to the deployment workload, and use a server certificate valid for `host.docker.internal`. Keep `ca.pem`, `cert.pem`, and `key.pem` in `/opt/campushire/config/parser-client-tls` with mode `0600`. OCI network controls must continue to deny external access to 2376. Never mount either host Docker socket into the worker.

Point a stable hostname at the reserved IP before deployment. `Caddyfile` obtains and renews a public certificate automatically, so ports 80 and 443 must reach the VM.

## GitHub staging environment

Configure these non-secret environment variables:

- `OCI_SSH_HOST`: reserved VM IP or SSH hostname
- `OCI_SSH_USER`: dedicated deployment user
- `STAGING_HOST`: public staging hostname without a scheme

Configure these environment secrets:

- `OCI_SSH_PRIVATE_KEY`: dedicated Ed25519 private key
- `OCI_SSH_HOST_KEY`: pinned `known_hosts` line captured out of band
- `POSTGRES_PASSWORD` and `REDIS_PASSWORD`: independent random values
- `GEMINI_API_KEY`: optional; omit it to exercise deterministic degraded behavior

The VM retains protected values only below `/opt/campushire/config`. Populated environment files, private keys, client certificates, and database dumps must never enter Git.

## Release sequence

1. Run the frontend `Publish frontend image` workflow with `https://<staging-host>/api/v1`.
2. Run the backend `Publish backend images` workflow.
3. Make the five GHCR packages public for the zero-cost staging target, or authenticate the VM using a read-only package token.
4. Copy the five digest-qualified references from the workflow summaries into `Deploy OCI staging`.
5. Approve the protected `staging` environment deployment.
6. Run synthetic seeding, staging smoke, parser isolation, dependency-failure, load, and recovery rehearsals.

The deployment refuses mutable tags, reserved example hosts, plaintext parser access, missing TLS material, non-ARM hosts, or world-readable protected configuration. Promotion involving real student resumes remains blocked until the managed parser policy, backup/restore evidence, privacy ownership, and representative UAT gates are accepted.
