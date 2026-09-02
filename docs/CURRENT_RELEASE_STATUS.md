# Current Release Status

Recorded: 2026-09-02 (Asia/Calcutta)

Decision: **GO for continued synthetic staging; NO-GO for real student data.**

This is the authoritative status record for the current two-repository CampusHire candidate.
Dated audits, dossiers, manifests, activation records, and completion documents remain historical
evidence for their exact source pair. They do not qualify later source changes.

## Current source and contract truth

| Item | Current evidence | Classification |
| --- | --- | --- |
| Frontend source baseline | `d38b3b3db1073720596962ff4b149fed1a6c82f5` | Latest source-changing commit before this status-only phase |
| Backend source baseline | `4e676b0598c4f5b3efae9e63c2d7de68bf805e73` | Latest source-changing commit before this status-only phase |
| OpenAPI SHA-256 | `b75c33f5e6de4f31660c119c6d1e6f6af4092d0f6c74af8f54cb1fbfe92fe11a` | Fresh backend export, backend snapshot, and frontend snapshot match |
| Alembic head | `20260902_0016` | Single head reported by `python -m alembic heads` |
| Frontend tests | 104 passed in 35 files | Fresh local baseline |
| Backend tests | 131 passed, 1 environment-gated skip | Fresh local baseline |
| Synthetic staging | `https://campushire.80-65-208-136.sslip.io` returned HTTP 200 | Reachable historical synthetic deployment; current-pair identity not proven |

The source baselines above identify the code inspected by Phase 0. Documentation-only commits that
record this status do not turn the pair into a frozen release candidate. Phase 10 must record the
final source SHAs, image digests, configuration hash, OpenAPI hash, migration head, signatures,
rollback pair, and runtime observations without combining candidates.

## Environment classification

| Boundary | Current decision | Reason |
| --- | --- | --- |
| Local development | Available for synthetic development and qualification | Fresh unit/integration baselines pass |
| Synthetic staging | GO to continue | Public endpoint is reachable; use synthetic data only |
| One-institution real-data pilot | NO-GO for the current source pair | Current artifacts, security delta, recovery/capacity evidence, representative UAT, and approvals are not sealed together |
| General production | NO-GO | Pilot evidence and wider availability/operations gates remain open |
| Multi-institution production | NO-GO | Tenant provisioning, quotas, support, isolation, capacity, and institutional onboarding evidence remain open |

## Evidence boundary

- The 2026-08-28 security closure is historical because authentication, recruitment,
  communications, UI, and migration code changed afterward.
- The 2026-08-29 pilot activation commits and their messages are not proof that the current source
  pair is deployed, approved, or monitored.
- The current frontend/backend OpenAPI snapshots are compatible, but compatibility alone does not
  authorize independent promotion.
- Representative student, T&P administrator, Safari/keyboard, and screen-reader acceptance cannot
  be inferred from automated tests.
- Institutional, privacy/legal, operational, budget, SLO, RPO/RTO, and final release authorization
  remain accountable external gates.

## Active execution sequence

Follow `plans/campushire-general-production-master-plan.md` from Phase 1 onward. Each phase must
pass its exit criteria, retain exact-candidate evidence, and use independently reversible
frontend/backend commits. No historical completion label may be reused without live verification.
