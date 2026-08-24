# Incident and Breach Communication Matrix — Approval Draft

## Response workflow

1. **Detect and preserve:** record UTC time, reporter, affected environment/tenant, candidate SHA/image, correlation IDs, and safe symptoms. Do not place secrets, resume contents, or student identity in tickets/chat.
2. **Triage:** classify data sensitivity, tenant reach, privilege gained, integrity/availability impact, active exploitation, and whether hiring/eligibility decisions may be affected.
3. **Contain:** revoke the narrow session/credential, disable the affected route/provider/worker/tenant feature, stop unsafe writes, and preserve evidence. Do not weaken CSRF, tenant, parser, or audit controls to restore service.
4. **Eradicate and recover:** patch from reviewed artifacts, rotate exposed credentials, restore from verified backups where required, and rerun tenant, migration, security, recovery, and smoke checks.
5. **Communicate:** the incident lead coordinates factual updates. Privacy/legal authority—not Codex or an engineer alone—decides whether, when, and how regulators, institutions, affected people, providers, or law enforcement are notified.
6. **Close:** record timeline, impact, decisions, evidence custody, follow-ups, owners, dates, and an approved post-incident review.

## Severity and communication matrix

| Condition | Provisional severity | Immediate roles | External communication authority |
| --- | --- | --- | --- |
| Confirmed cross-tenant or credential/session compromise; material resume/profile exposure | Critical | Incident lead, security, platform, privacy/legal, institution T&P, product | Privacy/legal with institution authority |
| Integrity failure in eligibility/application history; exploitable privilege escalation; sustained critical outage | High | Security/platform, product, T&P, privacy/legal as data is involved | Assigned legal/privacy or service owner |
| Bounded tenant/provider outage with durable recovery; no confirmed exposure | Medium | Platform/service owner, product support | Service owner under approved status policy |
| Cosmetic/low-impact issue without data or decision effect | Low | Product/support owner | Normally internal unless policy says otherwise |

## Required owner register

Incident commander, deputy, security lead, platform lead, privacy/DPO contact, legal authority, institution T&P contact, product owner, support lead, communications approver, provider escalation paths, and after-hours rotation are all **pending** in `docs/OPERATIONAL_OWNERSHIP.md`. Notification deadlines must be supplied by qualified institutional/legal owners; this draft deliberately invents none.
