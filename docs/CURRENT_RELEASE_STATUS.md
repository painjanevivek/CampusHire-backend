# Current Release Status

## Phase 8 revalidation — 2026-09-23

Decision: **NO-GO for real student data and production. Synthetic-only engineering validation is
complete for the source pair below; external gates remain open.**

This revalidation applies to Backend commit `532dd83056a95d0769b5d2f4991128688e921bd1` on
`phase/08-release-candidate` paired with Frontend commit
`533fd4e9c1d6fa5aa8fefed8815d07e3992acb9d` on `feat/landing-and-sign-in-experience`. Their recorded
parents are Backend `2dc5e56fd25a6bd028700adf92fff9212d06e615` and Frontend
`bf26df9e431d1364e66098705420aee984073f03`. Backend and Frontend OpenAPI snapshots match at SHA-256
`C58EF1A6271958173AAFA6FC60D9FE555C44C477E91634B8EBD649F8660E6D41`; the single code migration
head is `20260923_0038`.

The latest engineering checks pass: Backend `262 passed, 1 skipped`, Ruff, and strict MyPy across 149
source files; Frontend `287 passed` across 79 files, lint, typecheck, and production build. The public
production smoke passed four routes. Chromium accessibility passed all 24 route/viewport checks on
six public pages and four viewport sizes with zero axe violations, keyboard failures, or unexpected
browser console errors. The exact generated-client hash and focused contract evidence are recorded in
`PHASE_08_RELEASE_CANDIDATE.md` in each deployable.

This run added project type and a 300-character project-description limit to the onboarding contract,
allowed empty experience and project/skills stages, and kept required review and privacy confirmation
enforced. It corrected a wildcard-CORS bug in the accessibility harness's credentialed degraded-API
fixture; this did not change production CORS settings.

The institution still needs to define whether student signup itself must wait for a human admission
review. The current student signup endpoint can create an active session/membership, while institution
registration review is a separate workflow. Do not claim that student signup is institution-reviewed
until policy and backend behavior agree.

The local database remains at `20260923_0036`; it was not upgraded or modified. Only isolated
synthetic test databases were used. A live migration, staging restore, current-candidate security
approval, representative UAT, external support/alert ownership, capacity/cost evidence, artifact
provenance, legal/privacy decisions, and final authorization remain unverified. The
`REAL_DATA_AUTHORIZATION_LOG.md` was not changed; no deployment or real student data use is approved.

## Earlier Phase 8 validation record — superseded by the revalidation above

Decision: **NO-GO for real student data and production. Synthetic engineering qualification is
complete for this branch; external release gates remain open.**

This update describes the `phase/08-release-candidate` source pair descended from Backend
`ef790dd1aaea0f671bd17dd165ac3d8075f9ba45` and Frontend
`6d11b785be47a6aeb56956c99a339e8f7ced7115`. The final commit identifiers are the commits that
contain this record and are reported with the pushed branch. Backend and Frontend carry the same
reviewed OpenAPI SHA-256
`B92CE1B65543596FD23AB5D7B5A285405C7016F2983ED90702B34F27A890750E`; generated Frontend types
are byte-stable across repeated generation. Alembic has the single head `20260923_0036`.

The current engineering checks pass: Backend `258 passed, 1 skipped`, Ruff, and strict MyPy over
149 source files; Frontend `263 passed`, lint, typecheck, and production build. An isolated
PostgreSQL 17 rehearsal upgraded from an empty database through head, downgraded one revision,
rolled forward, created a logical backup, and restored to a separate database. It preserved the
synthetic record counts, application evidence digest, private-object reference, and queued-work
timestamp.

The current security work has two layers. Standard scan
`76a5a163-a664-43d6-8e18-064c59c83735` found one medium legacy operator-key authorization bypass
in the Backend parent. This branch removes those institution provisioning and registration-decision
routes, removes the bootstrap secret, and exposes institution provisioning only through the
authenticated singleton Platform Admin route with explicit permission, CSRF, recent MFA, actor
attribution, and `no-store` handling for its one-time invitation token. Focused tests prove the old
routes return `404` and the protected replacement rejects missing controls. Diff scan
`fa3026b5-a1a3-4ce7-b1bc-b06915465fef` reviewed all nine security-relevant Backend changes and
reported zero new findings. Frontend standard scan `31893d29-8c23-4f9e-b936-ffcade36a5fd`
reported zero findings across its nine reviewed surfaces. These are source reviews, not deployed
penetration tests or dependency-advisory certification.

The following gates remain blocked and prevent a `GO`:

- accountable legal/privacy, T&P, reporting, accessibility, IT/security, support, and cost
  approvals are absent;
- representative Student and Officer UAT is not signed;
- digest-qualified images, SBOM, provenance, signatures, rollback pair, and an approved registry
  promotion are not recorded for this source pair;
- an authorized staging deployment, named alert recipient, separate-host recovery rehearsal, and
  measured capacity/cost result are not present;
- Gemini model/privacy/billing approval and the institution's authenticated manual-code handoff
  procedure are not approved; and
- no final candidate-specific real-data authorization exists.

Historical evidence below retains its original scope and cannot be inherited by this candidate.

## Phase 0 baseline update — 2026-09-22

Decision: **NO-GO for real student data and production. Synthetic qualification only.**
This update describes the committed `phase/00-baseline` source pair. It is a reproducible
synthetic baseline, not a frozen or approved production release candidate. The pre-existing
résumé, identity, workspace, and content work was retained and separated into domain commits.

| Baseline item | Current observation |
| --- | --- |
| Backend functional source | `9286af6ba737b3936d4e6b2a00a3d8d2c28ad88f` |
| Frontend functional source | `b837679eae8390710a2e07278897823a6a567851` |
| Alembic head | `20260915_0033` (one head; no new migration in this work) |
| Reviewed OpenAPI snapshot | Backend and Frontend SHA-256 `8916A3B064C8AFB5CF676D27A148834F7A1EA5442D9DF93B83B35FBF881DB540` |

The first identity/delivery tranche is implemented in these working trees: student signup and
activation now require an invitation tied to a committed roster row and verified institution
domain; platform-assigned T&P staff can select among only their active institution memberships;
invitation and reset redemption lock the token row; and email-disabled roster/recovery workflows
issue one-time codes through an audited, no-store officer or platform Admin response. An unconfigured
sender suppresses delivery rather than reporting mail as sent. Deployment validation has an explicit
manual-handoff mode. The institution must still approve an actual authenticated handoff and
identity-check procedure; a configuration reference is not that approval.

Local verification for this source pair: Backend `242 passed, 1 skipped`, Ruff and strict MyPy
pass; Frontend `245 passed`, lint, typecheck, and production build pass. These checks
do **not** include a frozen paired commit/image, PostgreSQL concurrency rehearsal, migration
replay/restore, current security review, complete browser/accessibility UAT, real alert/backup
restore, provider/privacy approval, or the institutional sign-offs required below. The remaining
application-packet consolidation, agentic qualification, outcome/reporting semantics, deployed
privacy and recourse checks, and release gates remain open. Older evidence in this document is
historical and cannot qualify the present working trees.

Recorded: 2026-09-05 (Asia/Calcutta)

Decision: **Product-experience working trees implemented; continued synthetic qualification only;
NO-GO for real student data or production promotion.**

This is the authoritative status record for the current two-repository CampusHire candidate.
The identical machine-readable compatibility manifest is checked into both repositories at
`.github/release/pilot-compatibility-manifest.json`. Dated audits, dossiers, activation records,
and completion documents remain historical evidence for their exact source pairs and do not
qualify this candidate.

## Product experience upgrade — 2026-09-05

The new student-priority, correction-request, candidate-review, publishing, navigation, comparison,
preparation, notification, reporting, and landing interfaces are working-tree changes above Frontend
`7ac8f7704841fc9d6d0d4ca0bbd056186eb76504` and Backend
`d07997da878ff75e2166a341c0484a44ef00b17d`. These Git heads alone do not identify the new code.
The exact runtime/test source fingerprints and produced results are recorded in
[product-experience evidence](evidence/product-experience-20260905.json), with scope, reproduction,
rollout, and remaining gates in [the implementation record](PRODUCT_EXPERIENCE_UPGRADE.md).

Current automated source checks: Frontend 186 tests pass, typecheck/lint/build pass; Backend 182
tests pass with one skipped, Ruff and strict MyPy pass. The additive migrations through
`20260905_0022` applied to local PostgreSQL and compile as upgrade SQL. Real local synthetic browser
workflows exercised a student response and officer resolution, candidate Back navigation, comparison
and preparation, and explicit drive publication. The publishing walkthrough also exposed and
verified a fix for copied rules being inserted before their copied parent roles on PostgreSQL.

All seven existing local performance-budget routes pass after fixing publishing layout shift.
Warm navigation meets the <=500ms p95 laboratory target with 30 measured transitions per core flow.
This is small-fixture laboratory evidence, not production capacity or a 1,000-user guarantee.
Refer to the paired evidence for completed browser/accessibility results and their exact scope.

Final browser results: 92 responsive page/viewport checks pass at 390x844, 768x1024, 1440x900,
and 1920x1080. Chromium, Firefox, and WebKit each pass 60 public/authenticated accessibility
checks, with zero unexpected console errors; native keyboard traversal, reduced motion, forced
colors, and emulated zoom/reflow checks pass. These are automated results, not user feedback.

Remaining gates are explicit:

- `alembic check` fails on older model/database constraint and index representation differences;
  those existing constraints were retained, not dropped to manufacture a pass.
- `npm run api:check` exits nonzero because the intentional new contract differs from Git HEAD.
  Both exported contracts match and repeated generation is byte-stable. A clean committed-candidate
  check is pending; the immutable compatibility manifest below is unchanged.
- New-source security qualification, deferred historical security findings, PostgreSQL concurrent-
  officer stress qualification, large-fixture capacity, staging checks, representative user feedback,
  registry evidence, and accountable external approvals remain pending.

No new security scan or institutional approval is claimed. Historical Phase 10 results below remain
bound to their original source pairs and cannot be transferred to these working trees.

## Phase 10 security qualification update — 2026-09-03 (historical source pair)

The Windows worker-profile launch blocker is resolved. The Codex Security launcher prefers the
independently installed stable CLI on Windows; that executable was still `codex-cli 0.152.0` even
though newer desktop executables were present. Updating only that selected stable CLI to `0.152.1`
allowed the managed `codex_security_deep_scan_worker` read-only permission profile to start. No
filesystem denial or sandbox rule was weakened.

Two separate Deep Security Scans completed and sealed against the immutable source pair below:

| Target | Scan | Result | Coverage |
| --- | --- | --- | --- |
| Frontend `fa02ff057e075d03f7447bcfdc6d8c148d7c5748` | `b7508ff4-2926-4964-be3f-fb2b76da3167` | One validated low finding: plaintext non-loopback API origins could receive credentialed traffic | Partial; 8 deferred surfaces |
| Backend `cf8ceaa55e0cd7ad3cb016e5ab6f096b07e80e00` | `9feddc81-0803-492b-9a28-f7fa6662bdba` | Four medium and seven low occurrences; two low occurrences duplicate the same single-use-capability race | Partial; 36 deferred surfaces |

The frontend transport path is remediated in the current working tree by central API-origin
validation, non-loopback HTTPS enforcement, redirect refusal for credentialed fetches, and a
release-smoke assertion. Focused tests passed `37/37`; the full frontend suite passed `160/160`,
with lint, typecheck, and production build also passing.

The backend workflow-dispatch shell-injection path is remediated in the current working tree by
passing dispatch inputs through environment variables rather than interpolating them into Bash
program text. Its focused release-security tests passed `6/6`.

The following validated backend risks remain open and therefore keep real-data promotion blocked:

- TOTP replay and concurrent password-reset/recovery-code consumption require atomic database
  consumption, a migration, and PostgreSQL concurrency regressions.
- Unauthenticated durable account lockout and authentication timing require an approved abuse and
  recovery policy before changing sign-in semantics.
- Production image/evidence binding requires registry allowlisting plus cryptographic
  signature/provenance/SBOM/source verification; opaque references are not approval evidence.
- Python release dependencies still require complete platform locks and artifact hashes.
- Resume ingestion still requires approved per-user, tenant, and global capacity budgets.
- Deletion-record expiry/anonymization requires an approved retention and legal-hold period.

TAC advisory status was `not_granted` with no grant levels, so protected output display was not
assumed available. Scan token measurement was unavailable and is not reported as zero. Both scan
reports are source-review evidence only: they do not prove deployed configuration, external
approval, or the deferred coverage surfaces. The repositories advanced beyond the scanned pair
during qualification, and the remediations are not part of the immutable compatibility identity
below; a new candidate must be frozen and requalified before any promotion decision.

[Active real-data pilot dossier](REAL_DATA_PILOT_RELEASE_DOSSIER.md)

## Working-tree application packet qualification

Recorded: `2026-09-03T17:41:13Z`

The role-specific application packet implementation has passed internal synthetic qualification on
the current uncommitted Frontend and Backend working trees:

- Backend: `158 passed, 1 skipped`; Ruff clean; strict MyPy clean across 101 source files; Alembic
  reports the single head `20260903_0019` and the new migration compiles from `20260902_0018`.
- Frontend: `165 passed`; TypeScript clean; ESLint clean; the Next.js production build includes
  `/opportunities/[roleId]/apply`.
- Browser: the four-step existing-resume path, profile snapshot, optional compliance disclosure
  controls, review recovery after reload, accuracy gate, and `390 × 844` reflow were exercised with
  synthetic data in the Codex in-app browser.

This qualification is not a new immutable compatibility candidate. The mirrored phase-08/phase-09
manifest below remains unchanged because these working-tree changes do not yet have final commit
SHAs or registry-qualified image digests. A subsequent candidate must bind the committed Frontend
and Backend heads, regenerated OpenAPI digest, Alembic head, image digests, and fresh evidence
timestamps. External UAT, legal or institutional-policy approval, governance signoff, registry
promotion, signature/provenance, and authorized go/no-go remain unclaimed and pending.

## Active Phase 10 evidence references

| Gate | Candidate state | Accepted reference boundary |
| --- | --- | --- |
| Security qualification | Pending for this candidate | The 2026-08-28 Deep Scan closures are historical records bound to older frontend/backend revisions. They are not scan evidence for the phase-08/phase-09 pair. |
| Accountable approvals | Pending for this candidate | Historical conditional approvals and governance registers do not authorize this candidate. Candidate-specific controlled references must be attached to the active dossier. |

Historical records keep their original outcomes for auditability. Their dates, scan IDs, source
revisions, and conditions are scope labels—not transferable release evidence.

## Immutable compatibility identity

| Item | Bound value | Verification boundary |
| --- | --- | --- |
| Candidate | `campushire-frontend-phase-08_backend-phase-09_20260903` | Source compatibility verified; image records are non-authoritative |
| Canonical manifest SHA-256 | `44c8b729542b8f4ea1fe706fa6497b7a8f21180fdb7abd4dcc85969c02c9334c` | Checked by both CI validators against the adjacent immutable lock |
| Frontend phase-08 source | `fa02ff057e075d03f7447bcfdc6d8c148d7c5748` | Full commit and phase subject verified |
| Backend phase-09 source | `cf8ceaa55e0cd7ad3cb016e5ab6f096b07e80e00` | Full commit and phase subject verified |
| OpenAPI Git-blob SHA-256 | `dc90f81eb4802740ab932d82c0dc31a55d6d569e28a73a01700c218f78e83603` | Frontend, Backend, and both bound commits are byte-identical after checkout normalization |
| Alembic head | `20260902_0018` | Single head discovered from the bound Backend tree |
| Evidence recorded | `2026-09-03T13:28:44Z` | Manifest timestamp for source checks and non-reproducible local image records |

The Frontend image was built with
`NEXT_PUBLIC_API_URL=https://campushire.80-65-208-136.sslip.io/api/v1`. That build-time endpoint
selection is compatibility evidence, not proof that this exact candidate is deployed there.

## Non-authoritative local image record

| Component | Linux/AMD64 local Docker image ID |
| --- | --- |
| Frontend | `sha256:588b2bfd04f990f9fd7dd60137d90cf1c78b7c367c727828ac0dac3cd4f3aeb8` |
| Backend API | `sha256:d63ee698c3fbfefee4980d3fbc1edaaba6f27757ddb6a1042369ff68eec9f900` |
| Backend worker | `sha256:269890c16d1aeac9097a42af97a556c7ef8dba8db90be43080b28d6bed52acac` |
| Credential-free parser | `sha256:0d3e29678b8d46fe39176bd7cd7237466f7ffc508c3fb61aebc3331a54b1cb23` |
| ClamAV runtime | `sha256:45635d46ff58913cb875db692a2f0523348714409d782392fe48d44980e670c3` |

These identifiers record the images exercised during the historical local smoke run, but they are
not reproducible or independently attributable to a clean source checkout. They are not a CI trust
boundary, registry-qualified multi-architecture digests, signatures, attestations, or proof of
managed deployment, and they are intentionally excluded from the machine-verified compatibility
manifest. Promotion must build from a clean bound source checkout and separately verify
the registry digest, source revision, SBOM, provenance attestation, and signature for every image.

## CI compatibility gate

Frontend CI checks out the exact Backend phase-09 commit, and Backend CI checks out the exact
Frontend phase-08 commit. Both run the same validator and focused negative tests. The gate rejects:

- abbreviated or inconsistent source SHAs and phase labels;
- OpenAPI bytes that differ between either working tree or either bound commit;
- a migration head other than `20260902_0018`;
- malformed source bindings or UTC evidence timestamps;
- post-candidate product changes outside the validator-owned control-path policy, including dirty
  or untracked working-tree content;
- divergence between the mirrored manifest, lock, validator, and focused tests; and
- any claim that external UAT, governance, registry promotion, signing, provenance, or final
  authorization has passed without evidence.

## Environment classification

| Boundary | Current decision | Reason |
| --- | --- | --- |
| Local development | Available for synthetic development and qualification | Exact source, contract, migration, and local image identities are sealed together |
| Synthetic staging | GO to continue qualification | No real student data or release authority is implied |
| One-institution real-data pilot | NO-GO | Registry promotion, signing/provenance, representative UAT, governance signoff, and authorized go/no-go remain pending |
| General production | NO-GO | The real-data pilot gates are not closed |
| Multi-institution production | NO-GO | Pilot evidence and wider operational/tenant gates are not closed |

## External evidence boundary

The compatibility manifest deliberately records `pending` with `null` evidence for affected
security review, representative UAT, governance signoff, registry promotion,
signature/provenance, and authorized go/no-go. No
historical approval, synthetic exercise, automated browser run, or local image build substitutes for
those accountable external decisions. If either bound source commit, OpenAPI snapshot, migration
head, build parameter, or promoted image digest changes, create and verify a new candidate rather
than editing this identity in place.
