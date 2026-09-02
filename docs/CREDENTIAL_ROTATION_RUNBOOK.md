# Credential Rotation Runbook

This runbook is an engineering procedure, not an authorization to rotate production credentials.
The named Platform/SRE owner and release authority approve the window; privacy/security owners join
when compromise is suspected. Rotate before first real-data activation, every 90 days, after an
owner leaves, and immediately after suspected disclosure.

## Universal sequence

1. Identify the credential by provider ID and affected exact candidate; never copy its value into a ticket.
2. Confirm a current encrypted backup, rollback pair, support channel, and bounded maintenance window.
3. Create the replacement with least privilege and overlap the old credential only where supported.
4. Install it in the protected external secret location, preserving mode `0600` and ownership.
5. Redeploy the same immutable images and run readiness, tenant-negative, queue, and dependency probes.
6. Revoke the old credential, verify it can no longer authenticate, and watch failures for one alert window.
7. Record operator, approver, UTC timestamps, old/new credential IDs, reason, candidate, and test results—never values.

## Credential-specific checks

| Credential | Replacement and validation | Revocation / rollback boundary |
| --- | --- | --- |
| VM SSH | Add a new hardware-backed/operator key, verify pinned host identity and restricted login | Remove the old public key only after a second operator validates access; console recovery is the rollback |
| PostgreSQL | Create/alter the workload secret, update protected URL and secret file, test migration/read/write | Revoke old role/password after API and worker pools recycle; restore the prior secret only within the approved window |
| Redis | Rotate `requirepass` and URL together during a bounded restart, test authenticated ping and rate-limit behavior | Existing sessions may fail closed; never disable authentication for continuity |
| OCI SMTP | Create a new SMTP credential, send a synthetic transactional message, verify delivery/bounce evidence | Delete the old SMTP credential after the outbox drains; do not retry suppressed recipients |
| OCI object access | Prefer instance-principal policy review over static keys; test put/get/delete on a synthetic opaque key | Revert only the policy change, never make the bucket public or create a pre-authenticated resume directory |
| Parser mTLS | Issue new CA/client/server material, stage both trust sets, run the sandbox verifier | Remove old trust after worker/parser probes; never fall back to an unauthenticated Docker socket |
| CI deploy | Replace the scoped SSH/deployment secret and pinned host key, run a non-activating bundle validation | Revoke old secret after workflow validation; branch credentials must remain read-only where possible |
| Operator bootstrap / webhook | Replace with at least 32 random bytes and run a synthetic signed request | Revoke old value after audit evidence; never print request bodies |
| MFA encryption | Use an approved versioned key migration with dual-read/single-write and recovery rehearsal | Do not replace in place or make enrolled factors unreadable; requires Security and database review |
| Administrator MFA/recovery | Re-enrol or regenerate through accountable step-up and recovery workflow | Revoke old factors/codes and all other sessions; institutional identity verification is an external gate |

## Completion evidence

A rotation is complete only when the old credential is rejected, the new credential passes its
bounded workflow, logs contain no value, dependent queues are healthy, the exact candidate remains
identified, and the accountable owner signs the non-secret rotation record.
