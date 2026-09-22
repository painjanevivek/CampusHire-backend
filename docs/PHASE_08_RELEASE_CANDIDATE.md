# Phase 08 release-candidate record

Status: **engineering candidate complete; real-data and production decision remains NO-GO**.

## Candidate identity

| Item | Value |
| --- | --- |
| Branch | `phase/08-release-candidate` |
| Backend parent | `ef790dd1aaea0f671bd17dd165ac3d8075f9ba45` |
| Frontend parent | `6d11b785be47a6aeb56956c99a339e8f7ced7115` |
| Candidate commits | The Backend and Frontend commits containing this record; report the pushed SHAs together |
| OpenAPI SHA-256 | `B92CE1B65543596FD23AB5D7B5A285405C7016F2983ED90702B34F27A890750E` |
| Alembic head | `20260923_0036` (single head) |
| Data classification | Synthetic only |

## Engineering evidence

- Backend: 258 tests passed, one skipped; Ruff and strict MyPy pass over 149 source files.
- Frontend: 263 tests passed; lint, typecheck, and the Next.js production build pass.
- Backend and Frontend OpenAPI bytes match. A second generated-client pass produced the same
  `types.gen.ts` SHA-256.
- PostgreSQL 17 clean migration, one-revision rollback, roll-forward, logical backup, and
  separate-database restore pass with synthetic counts and evidence references preserved.
- `git diff --check` is part of the pre-commit gate for the intended phase files.

## Security disposition

Backend standard scan `76a5a163-a664-43d6-8e18-064c59c83735` reported one medium finding in the
Phase 7 parent: reusable `X-Operator-Key` routes could provision institutions and decide institution
registration without a Platform Admin session, MFA freshness, CSRF, or actor identity. Phase 8
removes those routes and their bootstrap secret. The supported provisioning route now requires the
singleton Platform Admin, `platform.institutions.manage`, authenticated CSRF, recent MFA, and audit
attribution; its one-time invitation response is `no-store`.

Backend working-tree diff scan `fa3026b5-a1a3-4ce7-b1bc-b06915465fef` reviewed all nine changed
security-relevant files and reported zero new findings. Frontend standard scan
`31893d29-8c23-4f9e-b936-ffcade36a5fd` reported zero findings in its reviewed parent surfaces.
Limitations remain: parent-only review, no deployed dynamic penetration test, and no external
dependency-advisory feed. Source review does not close external security approval.

## Unclosed release gates

The repository contains no current controlled references proving representative UAT, legal and
privacy approval, provider/privacy approval, named operational support, real alert delivery,
separate-host restore, measured pilot capacity and cost, digest-qualified image publication,
SBOM/provenance/signatures, or final authorization. Those rows remain blocked in
`REAL_DATA_AUTHORIZATION_LOG.md`.

Therefore:

- synthetic development and qualification may continue;
- no real student data may be loaded;
- no production or commercial readiness claim is authorized; and
- `main` must not receive this stacked branch until an explicit candidate-specific `GO` is recorded.
