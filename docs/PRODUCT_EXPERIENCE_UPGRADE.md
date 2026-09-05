# Product experience upgrade — working-tree qualification

Date: 2026-09-05. Scope: local synthetic qualification, not real-data release approval.

## Delivery map

| Phase | Implemented increment | Verification boundary |
| --- | --- | --- |
| 1 | Deterministic placement-actions-v2 priorities; application summaries; supplemental correction requests and actor/timestamp history; revision-checked review queue/detail and bulk confirmation; cache invalidation protection | Service and HTTP tests, component tests, real student response/officer resolution, consecutive selection and Back navigation |
| 2 | Five-step publishing guide over persisted drafts and staged editors; student Preparation navigation; grouped T&P sidebar/mobile menu; record-derived notification categories | Component tests and local PostgreSQL publishing walkthrough, including reload and explicit final confirmation |
| 3 | Two/three-role comparison; sorting and named student/institution-owned saved filters; browsing scroll restoration; role-specific preparation from reviewed sources | Component/service/ownership tests; real comparison and preparation walkthrough; explicit missing-mapping and stale-source states |
| 4 | Backend aggregate Reports and filtered drill-downs; landing journey and actual synthetic interface captures; measured queue/detail and opportunity-query improvements | Report reconciliation tests, query profiling, public/authenticated browser checks and performance evidence |

The two repositories remain uncommitted. These are reviewable working-tree increments, not four
separately released or approved production versions. See the paired source fingerprints and actual
test outcomes in `evidence/product-experience-20260905.json` when final verification is recorded.

## Data and authority

- Corrections are supplemental. Neither a response nor its resolution replaces an application's
  original profile, resume, rule, eligibility, or decision snapshots.
- A response may attach an existing owned, clean, reviewed resume. Referenced versions cannot be
  deleted through the resume-version workflow; officer downloads check the institution, parent
  application, request, event, and source owner.
- Request actions and review actions serialize on the application and reject stale supplied
  revisions with a conflict. Updated interfaces supply revisions; old contracts retain compatible
  optional fields during rollout. Bulk confirmation revalidates every selected record.
- Terminal application outcomes close outstanding requests with a recorded reason. Notification
  read state does not resolve a request. Appeals remain separate.
- Preparation uses exact recorded skill evidence and explicitly reviewed mappings, not inferred
  proficiency. No provider is invoked by visiting Preparation. Resume suggestions still require
  acceptance in the existing resume workspace.
- `reviewed_preparation_mappings` is an additive read-side catalog linked to an institution,
  approved template/version and node, requirement, reviewer, timestamp, and status. No real mapping
  approval was created. Institutions without reviewed mappings see the limitation. Mapping
  authoring/approval UI and new curriculum are not included; controlled content curation remains
  an institutional responsibility.
- Reports count the selected submission cohort. A request count can exceed the number of
  applications in its drill-down because one application can have several requests. First review
  turnaround includes the first recorded departure from submitted, including withdrawal. Closing
  drives use server-generated deadline bounds independent of the application cohort.

## Compatible rollout

1. Review and back up the existing database through the normal release process.
2. Deploy the additive backend and apply migrations through `20260905_0022` before frontend
   consumers. `0021` adds requests/history, saved views, notification references, and revisions;
   `0022` adds the reviewed preparation mapping catalog.
3. Deploy the frontend with the matching generated OpenAPI contract. No new paid service, Redis,
   stack change, deployment-provider dependency, or environment secret is required.
4. Roll back application versions compatibly if needed; retain the additive tables and newly
   recorded evidence. Do not use a destructive migration downgrade to erase responses.

The local PostgreSQL upgrade and offline upgrade SQL generation succeeded. `alembic check` still
fails on older model/database constraint representations: unique constraints versus unique indexes,
the existing audit creation-time index, and the existing drive-window check constraint. None of
these constraints was dropped or weakened to silence the check. This remains a release gate to
resolve before promotion.

`npm run api:check` compares generated files against Git HEAD and therefore exits nonzero for this
uncommitted contract change. Independent repeat generation is byte-stable, and the exported
frontend/backend OpenAPI files match. The clean-commit gate must be rerun after the candidate is
committed; its present failure is not reported as a pass.

## Reproduce local evidence

From Backend:

```text
python -m pytest -q
python -m ruff check .
python -m mypy app
python -m alembic check
python -m scripts.profile_experience_queries
```

From Frontend, with the configured local API and production frontend running:

```text
npm run typecheck
npm run lint
npm run test
npm run build
npm run api:check
python scripts/experience_workflows.py
python scripts/experience_publishing_check.py
python scripts/experience_browser_checks.py --output .data/experience-browser-final
python scripts/accessibility_matrix.py --base-url http://127.0.0.1:3001 --browser chromium --authenticated --output .data/experience-accessibility-final.json
python scripts/performance_matrix.py --base-url http://127.0.0.1:3001 --output .data/experience-performance-final.json
python scripts/navigation_performance.py --output .data/experience-navigation-final.json
```

Workflow scripts create supplemental requests or a duplicated published drive in the local
synthetic demo workspace. Do not point them at real student data. They retain workflow history
and do not export authentication state. Browser screenshots use explicitly synthetic accounts.

## Evidence limits

- Earlier navigation baselines measured actual links but used a weaker readiness condition.
  Final checks wait for actual content and selected-record identity. Do not report a percentage
  improvement from these non-equivalent measurements. Pre-change candidate-selection and drive-
  editor baselines were not captured and remain unavailable.
- The final navigation target is p95 <= 500 ms over 30 warm transitions per core flow on this
  documented local profile. It is not production latency or 1,000-concurrent-user evidence.
- The profiler records actual query counts/durations and an EXPLAIN ANALYZE queue plan. Small
  fixtures did not justify speculative new performance indexes or infrastructure. Eligibility
  filtering still evaluates available candidate roles in the service; large-fixture capacity
  qualification remains necessary.
- Automated task completion is not student/T&P usability feedback. No external usability signoff,
  staging approval, new security scan, registry promotion, or real-data approval was performed.
- Historical security scans and the immutable compatibility manifest do not qualify these new
  working trees. Preserve their original source boundaries.
