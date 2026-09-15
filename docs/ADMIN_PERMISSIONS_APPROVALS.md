# Workspace Permissions and Change Approval Matrix

## Implemented authorization

| Role | Effective application access | Current boundary |
| --- | --- | --- |
| `platform_admin` | Institutions, T&P accounts, platform settings/health, cross-institution reports and read-only placement records | Singleton platform authority with no active institution membership and no placement-decision mutations |
| `student` | Profile, resume, opportunities, applications, preparation, notifications, privacy requests and appeals | Own authenticated, institution-scoped workflows |
| `tnp_owner` / `tnp_admin` (Officer) | Student onboarding, companies, drives, applications, institutional policies, reasoned overrides and reports | Institution-scoped operational authority; T&P account provisioning belongs to the Platform Admin |
| `tnp_reviewer` (Reviewer) | Assigned application and appeal review plus approved policy context | Assigned cases only; cannot publish drives, run bulk actions, override decisions, manage students, or access platform controls |
| `tnp_auditor` (Auditor) | Institution reports, audit and authorised supporting records | Institution-scoped and read-only |

The frontend is not an authorization boundary. Backend role and institution checks remain authoritative.

## High-impact change controls

| Action | Implemented actor | Required pilot approval/evidence | Enforcement gap |
| --- | --- | --- | --- |
| Verify, suspend, or revoke a student membership | Officer | Roster authority, accountable reason, confirmation, audit event | No dual approval |
| Create, suspend, revoke, or change a T&P role | `platform_admin` | Institution selection, accountable reason, audit event, affected-session revocation | No dual approval |
| Transfer Platform Admin authority | Current `platform_admin` or approved operational command | Explicit target user, expected revision, reason, atomic transfer and affected-session revocation | Recovery still requires controlled infrastructure access |
| Publish/close drive or role | `tnp_owner`, `tnp_admin` | T&P owner, effective window, version evidence | No dual approval |
| Delete a draft drive | `tnp_owner`, `tnp_admin` | Recent MFA and immutable audit event | No dual approval |
| Publish eligibility rule set | `tnp_owner`, `tnp_admin` | Policy owner review, rule/version evidence | Same administrator can author and publish |
| Approve institutional policy or extraction proposal | Officer | Human review reason, version and source evidence | No dual approval |
| Change application status | Officer or assigned Reviewer | Assignment/revision check, authorised transition and student-safe reason | Reviewer is limited to assigned context |
| Apply bulk application decisions | `tnp_owner`, `tnp_admin` | Recent MFA, preview, reason, notification count, and audit event | No dual approval |
| Override application decision | `tnp_owner`, `tnp_admin` | Recent MFA, reason, required policy reference, and append-only before/after evidence | No dual approval |
| Reassign a case across staffing queues | Officer in own institution; Platform Admin for audited staffing support | Revision check, reason and append-only assignment history | Platform Admin cannot decide the case merits |
| Retry/cancel platform background job | `platform_admin` | Operator reason/ticket and event timeline | Recovery permissions must remain narrowly scoped |
| Deploy/migrate/restore/rotate secrets | Infrastructure identity outside app | Change record, peer approval, rollback owner | Provider/IAM controls pending |

Role, assignment, and tenant enforcement are implemented in backend dependencies and tenant-filtered services; the frontend only projects available actions. Dual control is not universally code-enforced. For the pilot, use least-privilege named accounts, time-bound access, a two-person external change record for configured high-impact actions, immutable audit review, and periodic membership recertification. These remain operational compensating controls, not claims of code-enforced approval.
