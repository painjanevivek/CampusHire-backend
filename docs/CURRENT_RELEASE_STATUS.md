# Current Release Status

Recorded: 2026-09-03 (Asia/Calcutta)

Decision: **Verified source-compatibility candidate; GO for continued synthetic qualification only; NO-GO
for real student data.**

This is the authoritative status record for the current two-repository CampusHire candidate.
The identical machine-readable compatibility manifest is checked into both repositories at
`.github/release/pilot-compatibility-manifest.json`. Dated audits, dossiers, activation records,
and completion documents remain historical evidence for their exact source pairs and do not
qualify this candidate.

## Phase 10 security qualification update — 2026-09-03

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
