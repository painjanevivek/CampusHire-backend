# Known Limitations Register

| ID | Limitation | Impact | Current control | Release owner / exit condition |
| --- | --- | --- | --- | --- |
| KL-001 | PDF parsing is not yet proven inside a credential-free OS sandbox. | A malicious document could consume worker resources or exploit the parser. | Quarantine, type/size/page limits, malware-scan state, bounded jobs, safe error codes. | Platform security: isolated parser runtime and abuse test must pass before pilot uploads. |
| KL-002 | Exhaustive Deep Security Scans require a managed read-only worker permission profile not available in this session. | Standard scans cannot prove exhaustive multi-agent coverage. | Separate standard scans, threat model, code tests, and the Deep Scan IDs/blocker are recorded. | Security owner: run and accept independent frontend/backend Deep Scans. |
| KL-003 | Pilot traffic, infrastructure topology, SLOs, and cost ceilings are not institution-approved. | Local timings cannot be represented as production capacity. | Reproducible baseline tooling and evidence labels distinguish local from staging. | Product/platform owners: approve budgets and run staging load. |
| KL-004 | Institutional retention, consent, appeal, and incident contacts are not supplied. | Deletion holds and governance communications cannot be finalized. | Explicit retention holds, privacy documentation, auditable overrides, no invented contacts. | Institution DPO/T&P owner: approve policy and contacts. |
| KL-005 | Human keyboard, screen-reader, student, and administrator UAT is not signed off. | Automated tests do not prove usability with representative users. | Axe shell checks, keyboard/mobile browser matrix, reduced-motion coverage, UAT pack. | Accessibility/product owner: complete and sign the pilot sessions. |
| KL-006 | Qdrant, object storage, malware scanner, Redis, and Gemini recovery were exercised through controlled adapters, not selected managed vendors. | Provider-specific recovery behaviour remains unknown. | Fail-closed/degraded paths and provider boundaries are tested; core eligibility is independent. | Platform owner: execute vendor staging drills and attach evidence. |

No item in this register is silently waived. A release decision must close it or record an authorized, time-bounded risk acceptance with owner and expiry.
