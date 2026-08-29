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

Schedule `backup.sh` nightly, `check_object_quota.sh` before upload windows, and `restore_rehearsal.sh` monthly on an isolated clean host. Follow `docs/FREE_FIRST_PRODUCTION_OPERATIONS.md` for alerts, rotations, incident paths, and paid-upgrade triggers.

## systemd scheduling

Install `deploy/production/systemd/campushire-backup.service` and
`deploy/production/systemd/campushire-backup.timer` on the dedicated host. The timer runs the
existing encrypted, off-host backup under the non-login `campushire` service account. Restore
rehearsals remain deliberately operator-started on a separate clean host; never schedule them
against the production database host.
