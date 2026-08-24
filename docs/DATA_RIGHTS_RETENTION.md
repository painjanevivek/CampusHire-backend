# Data Rights and Retention Schedule — Approval Draft

## Current technical behavior

An authenticated student can edit current profile data and submit `POST /api/v1/privacy/deletion-requests` with `DELETE MY CAMPUSHIRE DATA`. Without an application hold, authoritative account/profile/resume/readiness data is removed transactionally and opaque private-object deletion is retried durably. Existing applications block deletion because immutable decision inputs may require retention. There is no automated export, restriction, correction-case, hold-release, or retention-expiry workflow.

## Proposed request procedure

1. Receive a request through the approved institutional channel; never request a password or session token.
2. Verify identity using an approved out-of-band process and record request type, scope, received date, owner, and due date outside Git.
3. For current-profile correction, guide the student through the product. For historical application evidence, preserve the original snapshot and append a correction/review record; never rewrite history silently.
4. For export, assemble only institution-scoped data using an approved operator process, review for third-party data, encrypt delivery, and record completion. No ad-hoc database export is authorized by this draft.
5. For deletion, disclose any application hold before execution. Release a hold only under an approved policy and preserve the required audit evidence.
6. Record decision, approver role, evidence, delivery channel, and appeal route; exclude request content and personal data from source control.

## Retention schedule

| Data category | Current behavior | Proposed period / trigger | Approval owner |
| --- | --- | --- | --- |
| Sessions and rate-limit state | Session revocation/expiry; Redis is ephemeral | Approve maximum session and security-window duration | Security/platform |
| Profile, roadmap, saved roles, notifications | Retained until eligible deletion | Active account plus approved closure window | Institution T&P/privacy |
| Resume files, versions, extraction, suggestions | Retained until eligible deletion; objects deleted asynchronously | Active account plus approved placement-cycle window | Institution T&P/privacy |
| Applications, eligibility snapshots, status history, overrides | Application creates a deletion hold; historical inputs are immutable | Approved placement-cycle/legal-claim period, then reviewed disposal | Institution legal/privacy |
| Audit events | Retained; no automated expiry | Security/accountability period approved by event class | Security/privacy |
| Deletion cleanup records | Pseudonymous operational record retained; completed object keys cleared | Approved proof-of-deletion period | Privacy/platform |
| Logs and metrics | Deployment-defined; content must exclude secrets/resumes | Shortest operational/security period by log class | Security/platform |
| Backups | Deployment-defined | Approved encrypted rotation plus verified expiry | Platform/privacy |
| Semantic evidence/vectors | Database evidence deleted when eligible; Qdrant is not active | Same trigger as source evidence; Qdrant blocked until deletion exists | Product/privacy |

Every proposed period is pending. Until approved periods and disposal automation exist, the pilot must use synthetic/minimized data and record KL-004 rather than claim retention compliance.
