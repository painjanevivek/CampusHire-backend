# Bounded Free-First Production Operations

## Decision boundary

Production may be activated only on a dedicated OCI host carrying the operator-created `/etc/campushire-dedicated-production-host` attestation. Real student data must never share a VM with unrelated workloads. If an eligible Ampere A1 shape is unavailable, activation remains blocked; Oracle documents that Always Free capacity can be temporarily unavailable and that the home-region allocation is bounded to 2 OCPUs and 12 GB memory.

This is a single-host, single-region topology with no automatic failover. The initial public objective is 99.0% monthly availability, RPO 24 hours, and RTO four hours. Upgrade to paid or multi-node infrastructure before promising higher availability, when two consecutive months miss the objective, or when any capacity trigger below persists for three measurement windows.

Current platform assumptions must be rechecked at every release against Oracle's [Always Free resource limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm). As of this plan review, Oracle documents 20 GB combined Object Storage for an Always Free-only account and 50,000 monthly Object Storage API requests. The release guard is deliberately set lower: uploads stop at 14,000,000,000 bytes unless an approved environment-specific limit is smaller.

## Isolated topology

The immutable digest-pinned Compose candidate separates gateway, frontend, API, worker, parser launcher, PostgreSQL, Redis, Qdrant, and ClamAV roles. Only the Caddy gateway publishes ports. PostgreSQL, Redis, Qdrant, ClamAV, Docker, and the parser endpoint remain private. A real owned domain is mandatory; `sslip.io`, `nip.io`, and example domains are rejected.

Resume and generated PDF objects use one private OCI bucket through instance-principal authentication. The workload never creates public or pre-authenticated links. OCI documents encryption at rest and supports customer-managed Vault keys; bucket permissions must prevent public-bucket updates and should scope the dynamic group to object use in the production compartment. See Oracle's [Object Storage security guidance](https://docs.oracle.com/en-us/iaas/Content/Security/Reference/objectstorage_security.htm).

## Backup and restore

`deploy/production/backup.sh` performs a custom-format PostgreSQL backup, verifies its catalog, encrypts it with an age public recipient, writes a SHA-256 companion, and uploads it off-host. It retains seven daily and four weekly encrypted recovery points. Run it nightly from a protected systemd timer. The private age identity is held outside the VM and is supplied only to the isolated rehearsal operator.

Run `deploy/production/restore_rehearsal.sh` monthly on a clean host. It downloads the newest daily pair, verifies the ciphertext checksum, decrypts locally, restores into a digest-pinned ephemeral PostgreSQL container, and checks the migration record. Never point a rehearsal at the live database. Record elapsed time and validate the four-hour RTO.

Object lifecycle rules are defense in depth, not the sole retention mechanism. Oracle notes that lifecycle execution is best-effort and destructive deletions cannot be recovered; test lifecycle policies on synthetic objects first. See [Object Lifecycle Management](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/usinglifecyclepolicies.htm).

## Quota and capacity gates

Run `deploy/production/check_object_quota.sh` before every deployment and upload window. When it exits 2, set `OCI_OBJECT_UPLOADS_ENABLED=false`, publish a maintenance notice, preserve downloads/deletions, and pause new-institution onboarding. Never bypass malware scanning or delete accountable records to recover space.

Alert after three consecutive five-minute windows at CPU 70%, memory 75%, local disk or private object allocation 70%, API error rate 1%, or p95 latency at 80% of its route budget. Page immediately for a failed ready check, worker heartbeat beyond two lease periods, backup older than 30 hours, certificate expiry inside 14 days, database-pool use at 90%, terminal cleanup failure, or cross-tenant test failure. Retain the existing 750 ms ordinary-read, 1,000 ms dashboard/opportunity, and 1,500 ms write p95 budgets with a zero-error concurrency-10 minimum.

## Transactional email

Use a dedicated OCI SMTP IAM user, an approved sender on the owned domain, SPF, and DKIM. Oracle recommends storing SMTP credentials securely and rotating them periodically; credentials do not expire automatically and each IAM user has a bounded credential count. See [SMTP credentials](https://docs.oracle.com/en-us/iaas/Content/Identity/access/working-with-smtp-credentials.htm), [email security](https://docs.oracle.com/en-us/iaas/Content/Security/Reference/email_security.htm), and [DKIM setup](https://docs.oracle.com/en-us/iaas/Content/Email/Tasks/managing_dkim-setup_email_domain_with_dkim.htm).

Security and account messages have queue priority. Optional reminders stop near the configured monthly allowance. OCI automatically suppresses hard bounces and complaints; ingest bounce records and do not retry a suppressed recipient until the cause is resolved. See [suppression-list behavior](https://docs.oracle.com/en-us/iaas/Content/Email/Tasks/managingsuppressionlist.htm).

## Credential rotation and runbooks

Before activation, and every 90 days thereafter, rotate VM SSH, database, Redis, SMTP, object-storage/dynamic-group policy review, parser mTLS, CI deployment, operator bootstrap, webhook, MFA encryption, and administrator recovery credentials. Rotate immediately after personnel changes or suspected disclosure. Use overlapping credentials where supported, validate the new credential, then revoke the old one. Never print values to logs or store them in Git, images, backups, `.data`, or browser bundles.

Operational order is documented in `docs/RUNBOOKS.md` and `docs/DEPLOYMENT_RECOVERY.md`: startup, graceful shutdown, immutable deployment, application rollback, database restore, credential rotation, incident and breach response, malware/scanner outage, Gemini/Qdrant degradation, email/object quota exhaustion, and data-rights cleanup. Every action records operator, UTC time, candidate digests, correlation references, observed capacity, and validation outcome without personal data.
