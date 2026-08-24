# Administrator Permissions and Change Approval Matrix

## Implemented authorization

| Role | Effective application access | Current boundary |
| --- | --- | --- |
| `student` | Student profile, resume, opportunities, applications, roadmap, notifications, privacy deletion | Own authenticated, institution-scoped workflows |
| `tnp_admin` | Institution setup; all recruitment, intelligence-review, notification, worker-operations, and audit administration routes | Institution-scoped but broad; one admin can execute high-impact actions |
| `tnp_reviewer` | None | Role exists in the model but no API route authorizes it; do not assign for pilot duties |

The frontend is not an authorization boundary. Backend role and institution checks remain authoritative.

## High-impact change controls

| Action | Implemented actor | Required pilot approval/evidence | Enforcement gap |
| --- | --- | --- | --- |
| Verify institution membership | `tnp_admin` | Roster authority and audit event | No dual approval |
| Publish/close drive or role | `tnp_admin` | T&P owner, effective window, version evidence | No dual approval |
| Publish eligibility rule set | `tnp_admin` | Policy owner review, rule/version evidence | Same admin can author/publish |
| Approve AI policy/extraction proposal | `tnp_admin` | Human review reason and source evidence | Reviewer segregation not enforced |
| Change application status | `tnp_admin` | Authorized process and student-safe reason | Broad admin role |
| Override application decision | `tnp_admin` | Appeal/case and policy reference, before/after evidence | Policy reference optional in API; no dual approval |
| Retry/cancel background job | `tnp_admin` | Operator reason/ticket and event timeline | Same broad admin role |
| Deploy/migrate/restore/rotate secrets | Infrastructure identity outside app | Change record, peer approval, rollback owner | Provider/IAM controls pending |

Until narrower roles and technical separation-of-duties are implemented, use least-privilege named admin accounts, time-bound access, a two-person external change record for high-impact actions, immutable audit review, and periodic membership recertification. These are operational compensating controls, not claims of code-enforced dual control.
