# Governance-to-Implementation Cross-check

| Governance statement | Implemented evidence | Gap / release treatment |
| --- | --- | --- |
| Eligibility is deterministic and separate from semantic relevance | Versioned rule engine, immutable evaluation facts/results, semantic evidence stored separately | Institution must approve rules and review process |
| Missing evidence routes to review | Eligibility engine/tests produce manual review | No dedicated appeal case workflow |
| Student deletion is honest and durable | Exact confirmation, application hold, transactional deletion, durable object cleanup | Retention periods and hold release are not implemented |
| Current profile data can be corrected | Versioned profile endpoints and optimistic revision conflicts | Historical application snapshot correction needs operational append-only process |
| Students can export data | Not implemented | Manual approved process only; no product claim |
| Administrative actions are tenant-scoped and audited | Backend dependencies, institution filters, audit/status/override evidence | `tnp_admin` is broad; dual control and narrower reviewer access are not enforced |
| Reviewer role supports least privilege | `tnp_reviewer` enum exists | No route authorizes it; do not assign it as an operational capability |
| AI output is reviewed and bounded | Reviewed extraction/policy workflows, provider metadata, deterministic fallback | Provider approval, legal basis, and managed-staging evidence pending |
| Retention and audit access are governed | Deletion holds and audit records exist | Durations, readers, disposal jobs, and recertification pending |
| Incident communications are accountable | Technical runbooks preserve/contain/recover | Named contacts, deadlines, and after-hours coverage pending |

This cross-check intentionally distinguishes application controls from proposed institutional procedure. Unsupported promises must not be added to public copy or release evidence.
