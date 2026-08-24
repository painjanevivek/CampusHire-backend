# Immutable Candidate Evidence — 2026-08-24

Status: **Local immutable artifacts verified; registry promotion and release authorization pending**

The images below were built from clean `git archive` exports, never from the dirty backend worktree. The generated Docker archives and machine-readable manifests remain under `.data/` and are intentionally excluded from Git. These content identifiers prove a reproducible local candidate; they do not claim that an approved registry, signing identity, managed environment, or deployment authority exists.

## Candidate

| Artifact | Source / immutable identifier |
| --- | --- |
| Frontend source | `46b3fa8f3b19df437498787952fabdbbf5237b77` |
| Backend runtime source | `053244217dc3a51995ecd162a9a240f25ef00f1d` |
| Frontend image | `sha256:b50515fca49038611965d2c3953608c0f5854e0ca4c314fdfef1dfb785f505f7` |
| Backend API image | `sha256:50544b14c60b7e1096c2fca46c82048e17be5e658e932b177a84d0f9d6610834` |
| Backend worker image | `sha256:3ed9c4890e655f2aff13d710063d608f13e3215ac8dfa45d6b72a0f62eb885a2` |
| Credential-free parser image | `sha256:56523cea8e9cba9a53d0a5e6d76e520aa293e10e46a0d46113ea471b180d747c` |
| Candidate Docker archive | `sha256:169d415da3592ca0489ebf64673c0e119570fd417a1cbbe39345038f2227fbbf` |
| OpenAPI snapshot | `sha256:cdd29daf9ca99f96dc31e69e28afc2dd58aa4bb99a27f579457eb5e10f8f2ab4` |
| Configuration bundle | `sha256:bc3702619c4a467c9abfc11c8bfd0600121218190ac7765b5c24851500c0e896` |
| Migration head | `20260824_0010` |

`scripts/hash_release_configuration.py` deterministically frames and hashes both deployables’ environment inventories, Dockerfiles, gateway/compose topology, and Next.js deployment configuration. `scripts/build_release_candidate_manifest.py` rejects malformed or abbreviated evidence and now requires API, worker, parser, candidate archive, and rollback archive identifiers.

## Rollback pair

| Artifact | Source / immutable identifier |
| --- | --- |
| Frontend rollback source | `d07678bf9fe194d75619002b43c9eff38eac55ac` |
| Backend rollback source | `fc03b588113b8a2194665820296b21392d940917` |
| Frontend rollback image | `sha256:903ffc279061d264e16f17023e02b6a2943daee91455bd8c374d9a196ce0efe7` |
| Backend API rollback image | `sha256:c6eeff9e83fe555cfa65a759aff517c9c22c409956387adaa7550488177af9f9` |
| Backend worker rollback image | `sha256:3cef919f0101f4a5f8bd7d23d107664c4b639b112f947b7533964a18feb684a0` |
| Parser rollback image | `sha256:a58396a2eeedd9a9b951e12da63e58e0f2c6acff4e72f2007f16027120cbcb95` |
| Rollback Docker archive | `sha256:c7f5856197c014ace71da3cb89b57f55b7077ab02851aa04711275267c1b8d2f` |

Both frontend snapshots contain the same OpenAPI hash. The rollback frontend passed the four-route production security-header smoke, the rollback API returned HTTP 200 from `/api/v1/health/live`, and the rollback parser passed the no-network, no-credentials, non-root, read-only, dropped-capability, timeout-cleanup, and valid-PDF checks.

## Candidate verification

- The candidate frontend container passed the four-route release smoke from its production image.
- The candidate API container became live and returned the documented `database_unavailable` readiness response when intentionally started without PostgreSQL.
- The migration head was read from the candidate API image, not inferred from a filename.
- The candidate parser passed `scripts/verify_parser_sandbox.py` with no credentials or network and bounded cleanup.
- The strict manifest accepted every immutable identifier and retained only the dirty-worktree and external gate blockers.

## Promotion boundary

Before release, load or push these exact archives into the approved private registry, capture registry-qualified digests, attach the approved signing/provenance/SBOM evidence, and repeat smoke checks in managed staging. If any promoted digest differs, discard this evidence and rebuild/reverify the full pair. No local digest or archive authorizes deployment by itself.
