# Phase 7C local staging rehearsal evidence

- Date: 2026-08-24
- Data class: synthetic-only
- Environment: local Docker Desktop with a Caddy internal CA; not managed staging and not approved for real student data
- Backend source candidate: `3a8d09d3673c60551cb3c8c418e43cf2c93fa136` plus the Phase 7C change
- Frontend source candidate: `6318d76abd5a28a38d8cec1d8076db53ab40d1e2`

## Immutable local artifacts

| Artifact | Image ID | Runtime identity | Size |
| --- | --- | --- | --- |
| API | `sha256:69f3a9666e2880a01e4498811245e5a25d5cda9af4aa7a2276101975c017c75b` | `campushire` | 149,470,230 bytes |
| Worker | `sha256:09ed35771d162b58721119a74d1de623e1acfe09cf3a01fe2a0a3c2d3f45d6dd` | `campushire` | 169,012,027 bytes |
| Frontend | `sha256:323d9e802710446106ff7364deb3963ba179d131ae1d058db8fc0601ada0b179` | UID 1000 (`node`) | 104,107,424 bytes |
| Parser | `sha256:0c91679fcd38fdf2bf689d99d0c2abb9032fd663321585989d25d96ee6792160` | UID/GID 65532 | 70,457,421 bytes |

The provider-neutral Compose manifest SHA-256 is `0d300c06dfc82ab0fb1618d7d91b2777c5f95c8b600c17f261aabf70ab27e387`; the Caddy configuration SHA-256 is `c11147a751459dcd7a018076ef350dda5253ba2d837e40702deed278c44516ed`.

## Executed checks

1. Backend Ruff, strict MyPy over 92 source files, 75 pytest tests with one intentional container-gated skip, and the production API/worker image builds passed.
2. Frontend ESLint, TypeScript, 67 Vitest tests, production build, clean Linux `npm ci`, and standalone image build passed.
3. API and frontend images generated valid health responses; the API retained deterministic PDF generation, and the worker image exposed the pinned Docker client without running as root.
4. Caddy served the frontend and API through `https://localhost:8443` using its internal CA. HSTS, CSP, `nosniff`, and nonce-bearing frontend policy checks passed.
5. The idempotent seed created two institutions and reserved `example.com` identities only. Student sign-in/dashboard, administrator operations, and a cross-tenant membership request returning 403 passed.
6. The pinned ClamAV service became healthy and returned `clean=True` for a synthetic control. The staging-configured worker started once against PostgreSQL, authenticated Redis, ClamAV, and the Docker parser adapter.
7. The fully interpolated Compose model validated without emitting its protected inputs. Temporary containers, network, and volumes were removed after the rehearsal.

## External exit gates

This local rehearsal proves repository configuration and controlled topology, not provider behavior. Phase 7C still requires selected hosting accounts, DNS/public certificates, registry-published image digests, secret-manager injection, private managed storage, backup schedules, least-privilege service identities, an authenticated rootless parser launcher, and repetition of these checks in managed staging. No real student data may be used until those gates and the applicable governance/security approvals pass.
