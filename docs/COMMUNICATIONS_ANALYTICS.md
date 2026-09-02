# Communications and product analytics boundary

This document describes the production-connected Phase 7 behaviour. PostgreSQL is authoritative for delivery state, user preferences, support references, and privacy-minimized product events.

## Transactional email

- Invitation, password-reset, security, application-status, and deadline-reminder messages use fixed, escaped templates. Arbitrary administrator or student HTML is not accepted.
- Invitation and password-reset capability URLs are encrypted while queued and purged after delivery or terminal failure.
- Security and account messages have priority over application updates and reminders. Optional reminders are suppressed when disabled by the student or when the configured monthly quota threshold is reached.
- The worker claims delivery rows with `FOR UPDATE SKIP LOCKED`, records only safe failure codes, retries with bounded exponential backoff, and exposes tenant-scoped delivery state and manual retry to authorized administrators.
- Deadline reminders are generated only for active students who saved a currently published role, have not applied, and whose deadline falls inside the configured reminder window. The sweep is idempotent and stores a hashed reminder identity rather than a student identifier in the deduplication key.
- Provider bounce callbacks require the configured operator webhook credential. Email provider failure never changes the authoritative application or account record.

## User guidance and incident communication

The frontend Help center covers account access, profiles, eligibility, applications and appeals, resumes, roadmaps, privacy, accessibility, and placement administration. Support submissions reject common personal identifiers and return an internal reference.

The public status surface and global service banner distinguish maintenance from delayed transactional email. They do not disclose provider configuration or present an optional-service outage as loss of placement records.

## Product events

Events are recorded by successful backend transactions, not browser-only signals. The allowlist covers invitation acceptance, onboarding progress, profile completion, first opportunity view, first application submission, resume completion, roadmap selection, roster commit, role publication, operation errors/retries, and support requests.

Rows contain only institution, allowlisted event name, fixed route group, timestamp, and an optional SHA-256 deduplication digest. They must never contain resume text, grades, enrollment identifiers, protected attributes, tokens, free-form notes, email addresses, or raw user/resource identifiers. Funnel counts are operational/product diagnostics and must not be used to infer student worth or employability.

## Operational evidence

Completion requires tests for queue priority, preference and quota suppression, encrypted capability payloads, safe failures, owner invitation delivery, account security notices, deadline eligibility/exclusion, event idempotency, and the submission-event transaction boundary. OCI SMTP credentials, bounce-domain configuration, quota, and named incident ownership remain environment or external release gates.
