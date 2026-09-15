# Workspace authority migration

## Recorded baseline

- Backend baseline revision: `5074ec5319e0ce4dbdd1e898f2626d60fa878b6a`.
- Frontend baseline revision: `0a8ce700528885727b62aa22d387a2c6a20848b5`.
- Source migration predecessor: `20260915_0032`; workspace-authority head: `20260915_0033`.
- The local development database was upgraded from `20260914_0031` through both additive revisions and verified at `20260915_0033`.
- The reviewed backend OpenAPI document remains the contract source of truth.
- Both repositories contained pre-existing working-tree changes. The migration is additive and does
  not treat those changes as baseline-owned work.
- Real student data status remains **NO-GO** until the candidate completes the documented security,
  restore, privacy, accessibility, performance, and institutional release gates.

## Authority decision

`platform_admin` is a platform singleton and has no active institution membership. It can administer
institutions and T&P access and can read placement records across institutions, but it cannot make
placement decisions. Institution work remains owned by T&P Officers, Reviewers, and Auditors.

| Capability | Platform Admin | Officer | Reviewer | Auditor | Student |
| --- | --- | --- | --- | --- | --- |
| Platform settings and health | Manage | Notices | Notices | Notices | Relevant notices |
| Institutions and T&P access | Manage | Request | No | No | No |
| Placement records | Cross-institution read | Own institution | Assigned context | Own institution read | Own |
| Companies, drives, onboarding | No | Manage | No | Read where assigned | No |
| Applications | Read | Manage | Assigned only | Read | Submit/respond |
| Policies and overrides | No | Manage with evidence | Approved policy read | Approved policy read | Published terms |
| Appeals | Staffing reassignment only | Resolve when independent | Resolve when assigned and independent | Read | Submit/track |
| Reports and audit | Platform-wide | Institution operations | Assigned summary | Institution read | Personal history |

Backend permission checks own this matrix. Navigation is a projection of effective capabilities and
must never be the security boundary.

## Route transition

- `/api/v1/platform/*` is the explicit Platform Admin surface.
- `/api/v1/tnp/recruitment/*` is the canonical placement-operation surface.
- `/api/v1/admin/recruitment/*` remains temporarily available but is excluded from OpenAPI and is
  scheduled for removal after client migration.
- `/admin/*` is reserved for the Platform Admin UI; institutional staff use `/tnp/*`.
- Old T&P browser bookmarks redirect to their `/tnp/*` equivalent. Platform Admin record access is
  provided through read-only institution details, not through operational routes.

## Explicit Admin nomination

Preview the change:

```powershell
python scripts/migrate_platform_admin.py --user-id <uuid> --reason "Approved initial owner"
```

Apply only after reviewing the report:

```powershell
python scripts/migrate_platform_admin.py --user-id <uuid> --reason "Approved initial owner" --apply
```

The operation locks the singleton assignment, revokes affected sessions, removes active institution
membership from the nominee, converts legacy institution owners to Officers, and appends an audit and
transfer record. It never promotes every legacy owner.

## Rollout and rollback

1. Deploy migration `0033` and additive endpoints.
2. Nominate the exact Platform Admin with the dry-run command.
3. Deploy capability-aware sessions and the new workspace shells.
4. Regenerate the frontend client from the reviewed OpenAPI snapshot.
5. Remove hidden compatibility routes only after traffic and bookmark migration are verified.

UI presentation may be rolled back. The singleton authority boundary, assignment history, privacy
receipts, and audit records must not be removed during rollback.
