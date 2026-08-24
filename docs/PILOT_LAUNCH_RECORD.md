# Controlled Pilot Launch Record

Status: **Not launched — authorization and release gates pending**

## Immutable candidate

Record frontend/backend SHAs and image digests, OpenAPI hash, migration head, configuration-manifest hash, rollback pair, approved gate-evidence links, target environment, and deployment operator. Do not record secrets or personal data.

## Gradual rollout

| Stage | Scope | Entry evidence | Observation window | Decision / approver |
| --- | --- | --- | --- | --- |
| 0 | Synthetic operator smoke | Approved manifest, restore evidence, monitoring active | Pending | Pending |
| 1 | Authorized internal synthetic users | Security/accessibility/browser gates pass | Pending | Pending |
| 2 | Bounded institution pilot | Governance/UAT/go-no-go approved | Pending | Pending |

At each stage record health/readiness, error rate, latency percentiles, database/Redis saturation, queue age/retries/failures, scanner/parser/provider health, authorization/security events, restore readiness, and support observations. Compare only with approved thresholds and dataset labels.

## Stop and rollback record

Record trigger, UTC time, detector, affected tenant/workflow, action owner, traffic/worker state, rollback artifact, database decision, validation checks, communications authority, and recovery result. Never downgrade or overwrite a database without the migration-specific approved procedure and verified backup.

## Outcome

Record measured incidents, defects, metrics, participant feedback, accepted risks with expiry, follow-up owners/dates, and the named authority decision. Do not make unmeasured placement, fairness, hiring, performance, availability, or compliance claims.
