# Phase 6 security review

The Codex Security Standard Scan completed on the Phase 6A backend snapshot with two medium findings and no critical or high findings. The report is external to the repository so it cannot be mistaken for a current Deep Scan or production approval.

## Disposition

- **Semantic provider budget:** remediated in Phase 6B. Semantic evaluation is now a CSRF-protected `POST`, a Redis-backed per-user/institution fixed-window budget fails closed outside development, and Gemini receives an explicit timeout. Fingerprint caching and privacy-minimized projections remain in place.
- **Privileged PDF parser:** source boundary remediated in Phase 7A. Uploaded bytes now reach PyMuPDF only inside a minimal ephemeral container with no application credentials or network, stdin-only input, read-only root, dropped capabilities, and CPU/memory/PID/wall-time/file-size/output limits. The application retains PyMuPDF for deterministic output generation from reviewed structured fields, but the privileged upload-processing path has no native parser sink. Live policy, functional, hostile-input, timeout, and cleanup checks passed. The selected managed staging launcher must reproduce this policy before real student uploads.

## Remaining evidence

The user lifted the Deep Scan deferral on 2026-08-24. A separate Frontend Deep Scan was then launched, but discovery did not start because the managed scanner did not provide its required filesystem permission profile. Workflow rules prevented a same-response retry or substitute scan; the Backend Deep Scan remains pending behind the same managed capability. Neither repository is counted as passed or as a no-findings result. Managed-staging parser policy reproduction, staging tenant/IDOR testing, representative provider budgets, and institutional incident/privacy ownership remain real-data pilot gates. Dependency checks, parser abuse controls, and the provider-budget regression suite passed for the current candidate.
