# Shared-VM Staging Evidence — 2026-08-25

## Scope

CampusHire is deployed with synthetic data at
`https://campushire.80-65-208-136.sslip.io` on an Ubuntu 24.04 shared VM. The
deployment uses the committed staging Compose topology plus the shared-VM
override. It does not claim high availability or authorize real student data.

## Immutable release

| Component | Deployed immutable image |
| --- | --- |
| API | `ghcr.io/painjanevivek/campushire-api@sha256:e531ce4ccfb02b255bdc4873dbeb60629b5a639f6db1257f44349778c9c0fabc` |
| Worker | `ghcr.io/painjanevivek/campushire-worker@sha256:93a9bda91d2ee890e99ef9d3dd8ee36ade1fc1e21221b758e86f7954e541527e` |
| Parser | `ghcr.io/painjanevivek/campushire-parser@sha256:77c443a0d8f0d61683c4ae5de9a17eb98afbfa30e201f9e58dbfd09b5d19cd9e` |
| ClamAV | `ghcr.io/painjanevivek/campushire-clamav@sha256:3e545419b5c1791e6ce129fb57ebcebfdb290977fa9d00dcf28ce8057124bc46` |
| Frontend | `ghcr.io/painjanevivek/campushire-frontend@sha256:d6095b20bbee8455103ecc2507573d39909fbd476e47f316b75c3554e5fb765c` |

Application source is backend `f625a516de8050e11e2669dd64e37aea11007b9f`
and frontend `d32f8badd24bb1324994e190f8262ca7f43bce8b`. Image publication run
`32765188454` and protected deployment run `32766051011` passed.

## Boundary verification

- The shared Caddy gateway is the only public entry point. PostgreSQL, Redis,
  Qdrant, ClamAV, object storage volumes, API, and worker have no host ports.
- CampusHire retains separate edge, data, scanner-egress, and worker-egress
  networks. The existing `runner.evalarena.ai` workload remained online.
- The parser launcher is a separate rootless Docker daemon reached over mutual
  TLS. Parser jobs use stdin/stdout, run without mounts or network, and enforce
  non-root, read-only, capability, PID, memory, CPU, time, and output bounds.
- Root SSH password access is disabled. The deployment identity uses a pinned
  host key and a dedicated key-based account. Runtime secret files remain
  outside Git with restrictive permissions.

## Staging checks

HTTPS landing, API liveness/readiness, student and administrator journeys,
tenant-negative access (`403`), security headers, public browser rendering,
ClamAV readiness, degraded semantic matching, and the real resume worker path
passed. After verification, the CampusHire landing, liveness, readiness, and
the unrelated gateway workload all returned `200`; no disposable parser
container remained.

This closes the repository-controlled Phase 7C shared-VM staging work. Deferred
Deep Scans, representative UAT, governance review conditions, and real-data
authorization remain separate gates.
