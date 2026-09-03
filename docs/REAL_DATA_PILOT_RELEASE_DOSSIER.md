# Real-Data Pilot Release Dossier

Status: **Synthetic-only until every gate below is evidenced and Vivek Painjane records an
authorized decision.** This document is a controlled, privacy-safe index; it is never itself
approval and must not contain credentials, participant identities, private contact details, or
student data.

## Active candidate binding

| Field | Bound value |
| --- | --- |
| Candidate | `campushire-frontend-phase-08_backend-phase-09_20260903` |
| Canonical manifest | `.github/release/pilot-compatibility-manifest.json` |
| Canonical manifest SHA-256 | `44c8b729542b8f4ea1fe706fa6497b7a8f21180fdb7abd4dcc85969c02c9334c` |
| Security qualification | Pending; fresh affected review required for this candidate |
| Accountable approvals | Pending; candidate-specific controlled references required |

Only references explicitly attached to this candidate binding can close a gate. The dated Phase 10
security closures, governance register, conditional 2026-08-24 approval, staging records, and
earlier dossiers remain historical evidence for their recorded source pairs and conditions; none
is active evidence for this phase-08/phase-09 compatibility candidate.

## Pilot charter

| Control | Approved operational baseline | Evidence required before activation |
| --- | --- | --- |
| Release authority | Vivek Painjane (final `GO` / `NO-GO`) | Authorized decision record in the institution-controlled system |
| Institution scope | Exactly one institution | Institution identifier held outside Git; controlled reference recorded |
| Student limit | 500 registered students | Product and platform approval |
| Administrator limit | 10 administrators | T&P owner approval |
| Demand limit | 12 sustained / 20 burst requests; 1,000 uploads monthly | Managed load evidence and capacity approval |
| Availability objective | 99.0% monthly, excluding announced maintenance | Product and platform approval |
| Recovery objective | RPO 24 hours; RTO 4 hours | Isolated production-host restore rehearsal |
| Monthly cost ceiling | USD 300 | Provider-rate source, date, and Vivek's written approval |

No automatic failover, multi-institution onboarding, or real-data activation is authorized by
this charter. OCI capacity unavailability is a `NO-GO`, not a reason to reuse the shared staging
host.

## Accountable review and operational coverage

Approved names, contact methods, and coverage schedules are retained in the institution's
controlled operations system. Before activation, the release operator records the controlled
reference, approver role, decision date, expiry, and backup coverage for each row below.

| Gate | Required accountable role | Required independent evidence |
| --- | --- | --- |
| Product release decision | Vivek Painjane | Final decision after every other gate is closed |
| Placement policy and operational acceptance | Institution T&P owner | One-drive shadow review and administrator UAT acceptance |
| Privacy, retention, rights, and breach response | Institution privacy/legal authority | Signed review of the controlled policy versions |
| Accessibility acceptance | Qualified accessibility reviewer | Safari/macOS, keyboard, and screen-reader session results |
| Security and release platform | Security/platform owner | Managed staging, recovery, credential-rotation, and artifact evidence |
| Support, audit, and incident response | Support and audit custodians | Severity targets, escalation coverage, audit-reader approval, and incident contacts |

Vivek may coordinate every gate but cannot self-certify representative participant experience or
replace an independent institutional privacy/legal or accessibility review.

## Required immutable evidence

The generated strict release manifest must record all of the following from the approved private
registry and release archive: frontend/API/worker/parser digests, candidate and rollback archive
hashes, SBOM bundle hash, provenance/signature references, OpenAPI hash, migration head,
configuration-manifest hash, and rollback source pair. Any mismatch invalidates the candidate.

## Release decision protocol

1. The release operator verifies the strict manifest has no blockers and attaches a controlled
   reference to each gate's evidence.
2. Independent reviewers record `approve`, `approve with time-bounded conditions`, or `reject`
   outside Git. A rejected or expired decision is a release blocker.
3. Vivek records the final `GO` or `NO-GO`. A `GO` permits only the chartered institution and
   capacity envelope; all other institutions remain blocked.
4. The first activation uses the progressive launch record and rollback pair. Any stop condition
   returns the environment to synthetic-only operation until a new decision is recorded.
