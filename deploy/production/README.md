# Dedicated OCI production target

This target promotes the synthetic OCI staging topology to a bounded real-data candidate only after Phase 10 approval. It is deliberately single-region and single-host: 99.0% monthly availability, 24-hour RPO, four-hour RTO, and no automatic failover.

## Host contract

- Dedicated OCI Ampere A1 ARM64 VM; no unrelated workloads or datasets.
- Real owned domain with ports 80/443 routed to Caddy; SSH restricted to operators.
- OCI CLI and age installed for quota, backup, and restore automation.
- Instance principal in a production dynamic group with least-privilege access to one private bucket.
- `/etc/campushire-dedicated-production-host` created only after the isolation review.
- Rootless, mutually authenticated parser launcher retained from the staging contract.

If dedicated eligible capacity is unavailable, stop. Do not place production on the shared staging host.

## Protected environment

Keep `/opt/campushire/config/production.env` mode `0600` and outside the checkout. In addition to the staging database, Redis, parser, and digest-qualified image variables, configure:

- `PRODUCTION_HOST`, plus matching one-item `FRONTEND_ORIGINS` and `TRUSTED_HOSTS` JSON arrays
- `DATABASE_URL` and `REDIS_URL` for the private Compose-only PostgreSQL and authenticated Redis
- `PRODUCTION_SECRET_DIR=/opt/campushire/config/secrets`, containing only `postgres_password` and
  `redis_password` files with mode `0600`
- `PARSER_DOCKER_HOST=tcp://host.docker.internal:2376` and an absolute
  `PARSER_CLIENT_CERT_DIR` outside the checkout
- `OCI_OBJECT_NAMESPACE`, `OCI_OBJECT_BUCKET`, `OCI_OBJECT_QUOTA_BYTES=14000000000`, and `OCI_OBJECT_UPLOADS_ENABLED=true`
- `BACKUP_AGE_RECIPIENT`; keep `BACKUP_AGE_IDENTITY_FILE` off-host and use it only during rehearsal
- regional OCI SMTP endpoint, workload SMTP credential, approved from-address, and bounce webhook key
- independent operator bootstrap and MFA encryption keys
- `PRODUCTION_CADDYFILE_PATH=/opt/campushire/current/deploy/production/Caddyfile`

Run the validator without displaying values:

```text
python3 -m scripts.validate_production_environment /opt/campushire/config/production.env
```

## Operations

Deploy only immutable image digests:

```text
deploy/production/deploy.sh
```

Schedule `backup.sh` nightly, run `operations_check.sh` every five minutes, and run `restore_rehearsal.sh` monthly on an isolated clean host. The operations check retains a metrics-only record for API readiness, required container health, object-upload guard state, disk use, backup freshness, and certificate life. CPU, memory, route latency/error rate, database-pool use, and worker lease age still come from the approved monitoring export used by the signed activation snapshot. Follow `docs/FREE_FIRST_PRODUCTION_OPERATIONS.md` for alerts, rotations, incident paths, and paid-upgrade triggers.

## systemd scheduling

Install and enable both timer pairs under `deploy/production/systemd/`:

- `campushire-backup.service` / `.timer` for the nightly encrypted database plus private-object-manifest recovery bundle;
- `campushire-operations-check.service` / `.timer` for five-minute readiness and recovery-boundary evidence.

Both run under the non-login `campushire` service account with a read-only system view and private temporary storage. Configure the host monitoring/notification system to page on either unit entering `failed`; a timer without a consumed failure alert is not a monitoring system. Restore rehearsals remain deliberately operator-started on a separate clean host and must never run against the production database host.

After the dedicated host and non-login account are provisioned, install the units once with:

```text
sudo /opt/campushire/current/deploy/production/install_host_units.sh
```

Re-run the installer after a reviewed unit-file change. Application deployments do not silently
replace privileged host configuration.
