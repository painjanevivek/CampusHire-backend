# Administrator Permissions and Change Approval Matrix

## Implemented authorization

| Role | Effective application access | Current boundary |
| --- | --- | --- |
| `student` | Student profile, resume, opportunities, applications, roadmap, notifications, privacy deletion | Own authenticated, institution-scoped workflows |
| `tnp_owner` | Student enrollment, administrator-role assignment, recruitment, application review, intelligence review, operations, and audit | Institution-scoped; administrator-role changes require recent MFA, an accountable reason, and a different active owner for self/last-owner changes |
| `tnp_admin` | Student enrollment, recruitment, application review, intelligence review, operations, and audit | Institution-scoped; cannot assign or alter administrator memberships |
| `tnp_reviewer` | Recruitment read, individual application review, appeal resolution, intelligence review, and operations read | Institution-scoped review duties; cannot override decisions, apply bulk decisions, publish recruitment records, manage enrollment, manage workers, or read audit exports |
| `tnp_auditor` | Recruitment read, operations read, and audit read/export | Institution-scoped and read-only; cannot change recruitment, application, membership, or worker state |

The frontend is not an authorization boundary. Backend role and institution checks remain authoritative.

## High-impact change controls

| Action | Implemented actor | Required pilot approval/evidence | Enforcement gap |
| --- | --- | --- | --- |
| Verify or change a student membership | `tnp_owner`, `tnp_admin` | Roster authority, recent MFA for direct changes, accountable reason, audit event | No dual approval |
| Assign or alter an administrator membership | `tnp_owner` | Recent MFA, accountable reason, audit event; self-change and removal of the last active owner are denied | No dual approval |
| Publish/close drive or role | `tnp_owner`, `tnp_admin` | T&P owner, effective window, version evidence | No dual approval |
| Delete a draft drive | `tnp_owner`, `tnp_admin` | Recent MFA and immutable audit event | No dual approval |
| Publish eligibility rule set | `tnp_owner`, `tnp_admin` | Policy owner review, rule/version evidence | Same administrator can author and publish |
| Approve AI policy/extraction proposal | `tnp_owner`, `tnp_admin`, `tnp_reviewer` | Human review reason and source evidence | No dual approval |
| Change application status | `tnp_owner`, `tnp_admin`, `tnp_reviewer` | Authorized process and student-safe reason | Reviewer can execute the complete review transition |
| Apply bulk application decisions | `tnp_owner`, `tnp_admin` | Recent MFA, preview, reason, notification count, and audit event | No dual approval |
| Override application decision | `tnp_owner`, `tnp_admin` | Recent MFA, reason, required policy reference, and append-only before/after evidence | No dual approval |
| Retry/cancel background job | `tnp_owner`, `tnp_admin` | Operator reason/ticket and event timeline | Same broad operations role can retry or cancel |
| Deploy/migrate/restore/rotate secrets | Infrastructure identity outside app | Change record, peer approval, rollback owner | Provider/IAM controls pending |

Role and tenant enforcement is implemented in backend dependencies and tenant-filtered services; the frontend only explains available actions. Dual control is not code-enforced. For the pilot, use least-privilege named accounts, time-bound access, a two-person external change record for high-impact publication and decision changes, immutable audit review, and periodic membership recertification. These remain operational compensating controls, not claims of code-enforced approval.
