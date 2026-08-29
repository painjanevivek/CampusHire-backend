# Controlled Pilot Launch Record

Status: **Not launched — authorization and release gates pending**

Use [the real-data pilot release dossier](REAL_DATA_PILOT_RELEASE_DOSSIER.md) as the controlled
source for charter limits, independent review, and final authorization. This launch record begins
only after its strict manifest has no blockers.

## Approval authority

| Field | Recorded value |
| --- | --- |
| Named final approver | Vivek Painjane (Admin) |
| Decision | Approved with prerequisites |
| Decision date | 2026-08-24 |
| Effective condition | Staging, recovery, representative UAT, governance reviews, and the deferred frontend/backend security scans must pass |

This approval names the final project authority now, but it is not an immediate `GO` and does not waive any entry gate below.

## Immutable candidate

| Field | Controlled value / status |
| --- | --- |
| Frontend runtime source | `46b3fa8f3b19df437498787952fabdbbf5237b77` |
| Backend runtime source | `053244217dc3a51995ecd162a9a240f25ef00f1d` |
| Frontend image | `sha256:b50515fca49038611965d2c3953608c0f5854e0ca4c314fdfef1dfb785f505f7` |
| Backend API image | `sha256:50544b14c60b7e1096c2fca46c82048e17be5e658e932b177a84d0f9d6610834` |
| Backend worker image | `sha256:3ed9c4890e655f2aff13d710063d608f13e3215ac8dfa45d6b72a0f62eb885a2` |
| Credential-free parser image | `sha256:56523cea8e9cba9a53d0a5e6d76e520aa293e10e46a0d46113ea471b180d747c` |
| OpenAPI SHA-256 | `cdd29daf9ca99f96dc31e69e28afc2dd58aa4bb99a27f579457eb5e10f8f2ab4` |
| Migration head | `20260824_0010` |
| Configuration-manifest hash | `sha256:bc3702619c4a467c9abfc11c8bfd0600121218190ac7765b5c24851500c0e896` |
| Rollback source pair | Frontend `d07678bf9fe194d75619002b43c9eff38eac55ac`; backend `fc03b588113b8a2194665820296b21392d940917` |
| Artifact and gate evidence | [Immutable candidate evidence](IMMUTABLE_CANDIDATE_EVIDENCE_2026-08-24.md); [release evidence matrix](RELEASE_EVIDENCE_MATRIX.md) |
| Registry promotion / signing | Pending approved private registry and signing identity |
| Target environment | Pending selected managed staging target |
| Deployment operator | Pending named authorized operator |

These values describe the locally verified immutable runtime pair. Before Stage 0, reconcile them against the generated strict manifest and registry-qualified digests; any mismatch invalidates this record. Do not record secrets or personal data.

## Gradual rollout

| Stage | Scope | Entry evidence | Observation window | Decision / approver |
| --- | --- | --- | --- | --- |
| 0 | Synthetic operator smoke | Approved manifest, restore evidence, monitoring active | Pending | Vivek Painjane (Admin), subject to entry evidence |
| 1 | Authorized internal synthetic users | Security/accessibility/browser gates pass | Pending | Vivek Painjane (Admin), subject to entry evidence |
| 2 | Bounded institution pilot | Governance/UAT/go-no-go approved | Pending | Vivek Painjane (Admin), conditionally approved after every prerequisite passes |

At each stage record health/readiness, error rate, latency percentiles, database/Redis saturation, queue age/retries/failures, scanner/parser/provider health, authorization/security events, restore readiness, and support observations. Compare only with approved thresholds and dataset labels.

Before admitting the chartered institution or reopening an onboarding window, run the sanitized
health guard in `docs/PILOT_ACTIVATION_CONTROL.md`. A pause result blocks new onboarding but must
not bypass data-rights, deletion, download, or support workflows.

## Stop and rollback record

Record trigger, UTC time, detector, affected tenant/workflow, action owner, traffic/worker state, rollback artifact, database decision, validation checks, communications authority, and recovery result. Never downgrade or overwrite a database without the migration-specific approved procedure and verified backup.

## Outcome

Record measured incidents, defects, metrics, participant feedback, accepted risks with expiry, follow-up owners/dates, and the named authority decision. Do not make unmeasured placement, fairness, hiring, performance, availability, or compliance claims.
