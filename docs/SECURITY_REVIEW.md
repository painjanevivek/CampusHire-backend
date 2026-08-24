# Phase 6 security review

The Codex Security Standard Scan completed on the Phase 6A backend snapshot with two medium findings and no critical or high findings. The report is external to the repository so it cannot be mistaken for a current Deep Scan or production approval.

## Disposition

- **Semantic provider budget:** remediated in Phase 6B. Semantic evaluation is now a CSRF-protected `POST`, a Redis-backed per-user/institution fixed-window budget fails closed outside development, and Gemini receives an explicit timeout. Fingerprint caching and privacy-minimized projections remain in place.
- **Privileged PDF parser:** open deployment gate. Student PDFs are size/type bounded, quarantined, scanned by mandatory ClamAV outside development, parsed in a separately supervised worker, and never served before a clean result. However, PyMuPDF still runs in a process with material database/object-store access. Real student data is blocked until parsing moves to a credential-free sandbox with CPU, memory, wall-time, read-only input, and bounded output.

## Remaining evidence

Separate frontend and backend Deep Security Scans were attempted but could not obtain the required managed read-only worker profile. The user explicitly deferred them on 2026-08-24; they are not counted as passed or as no-findings results. Parser sandbox/abuse testing, staging tenant/IDOR testing, representative provider budgets, and institutional incident/privacy ownership remain real-data pilot gates. Dependency checks and the provider-budget regression suite passed for the current candidate.
